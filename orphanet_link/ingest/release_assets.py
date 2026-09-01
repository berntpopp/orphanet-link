"""Bounded retrieval of the exact assets from one GitHub data release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from orphanet_link.exceptions import DownloadError
from orphanet_link.ingest.download_security import (
    DownloadPolicy,
    open_validated_stream,
    stream_atomic,
)
from orphanet_link.ingest.release_identity import (
    ASSET_NAME,
    MAX_ASSET_BYTES,
    MAX_METADATA_BYTES,
    RELEASE_ASSETS,
    ReleaseIdentityError,
    validate_release_id,
)

_API_HOST = "api.github.com"
_ASSET_HOSTS = frozenset({_API_HOST, "release-assets.githubusercontent.com"})
_METADATA_SECONDS = 20.0
_ASSET_SECONDS = 120.0
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class ReleaseAssetError(ValueError):
    """GitHub release metadata or an asset failed the release boundary."""


@dataclass(frozen=True)
class ExistingRelease:
    """Authenticated state returned after fetching the exact remote asset set."""

    is_draft: bool
    release_id: int
    tag_name: str
    target_commitish: str
    immutable: bool
    complete: bool


def _read_bounded(response: httpx.Response, *, max_bytes: int, max_seconds: float) -> bytes:
    raw_length = response.headers.get("Content-Length")
    if raw_length is not None:
        try:
            if int(raw_length) > max_bytes:
                raise ReleaseAssetError("release metadata exceeds the size bound")
        except ValueError:
            raise ReleaseAssetError("release metadata has an invalid Content-Length") from None
    started = time.monotonic()
    body = bytearray()
    for chunk in response.iter_bytes(min(1 << 16, max_bytes + 1)):
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ReleaseAssetError("release metadata exceeds the size bound")
        if time.monotonic() - started > max_seconds:
            raise ReleaseAssetError("release metadata exceeded the deadline")
    return bytes(body)


def _release_assets(
    value: object, repo: str, tag: str
) -> tuple[int, str, str, bool, bool, tuple[Mapping[str, object], ...]]:
    if (
        not isinstance(value, dict)
        or type(value.get("tag_name")) is not str
        or value["tag_name"] != tag
        or type(value.get("target_commitish")) is not str
        or not value["target_commitish"]
        or type(value.get("draft")) is not bool
        or type(value.get("immutable")) is not bool
    ):
        raise ReleaseAssetError("release metadata has an invalid tag or source identity")
    try:
        release_id = validate_release_id(value.get("id"))
    except ReleaseIdentityError as error:
        raise ReleaseAssetError(str(error)) from error
    if value["draft"] is False and value["immutable"] is not True:
        raise ReleaseAssetError("published release is not immutable")
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise ReleaseAssetError("release metadata has an invalid asset inventory")
    by_name: dict[str, Mapping[str, object]] = {}
    asset_ids: set[int] = set()
    for asset in assets:
        if not isinstance(asset, dict) or type(asset.get("name")) is not str:
            raise ReleaseAssetError("release metadata has an invalid asset inventory")
        try:
            asset_id = validate_release_id(asset.get("id"))
        except ReleaseIdentityError as error:
            raise ReleaseAssetError("release asset ID is outside the safe bound") from error
        if asset_id in asset_ids:
            raise ReleaseAssetError("release metadata has an invalid asset inventory")
        name = asset["name"]
        if name in by_name:
            raise ReleaseAssetError("release metadata has a duplicate asset")
        by_name[name] = asset
        asset_ids.add(asset_id)
    names = set(by_name)
    if names - RELEASE_ASSETS or (not value["draft"] and names != RELEASE_ASSETS):
        raise ReleaseAssetError("release metadata has an inexact asset inventory")
    return (
        release_id,
        value["tag_name"],
        value["target_commitish"],
        value["draft"],
        value["immutable"],
        tuple(by_name[name] for name in sorted(names)),
    )


def _asset_facts(asset: Mapping[str, object], repo: str) -> tuple[str, int, str]:
    identifier = asset.get("id")
    url = asset.get("url")
    size = asset.get("size")
    digest = asset.get("digest")
    try:
        validate_release_id(identifier)
    except ReleaseIdentityError as error:
        raise ReleaseAssetError(str(error)) from error
    expected_url = f"https://{_API_HOST}/repos/{repo}/releases/assets/{identifier}"
    if type(url) is not str or url != expected_url:
        raise ReleaseAssetError("release asset URL is not bound to its API asset ID")
    if type(size) is not int or not isinstance(digest, str):
        raise ReleaseAssetError("release metadata has an invalid asset")
    match = _DIGEST.fullmatch(digest)
    if (
        match is None
        or size < 0
        or size > (MAX_METADATA_BYTES if asset["name"] != ASSET_NAME else MAX_ASSET_BYTES)
    ):
        raise ReleaseAssetError("release metadata has an invalid asset")
    return url, size, match.group(1)


def _local_asset_facts(expected_dir: Path, name: str) -> tuple[int, str]:
    path = expected_dir / name
    try:
        info = path.lstat()
        if not path.is_file() or path.is_symlink():
            raise ReleaseAssetError("expected package asset is missing or unsafe")
        max_bytes = MAX_ASSET_BYTES if name == ASSET_NAME else MAX_METADATA_BYTES
        if info.st_size > max_bytes:
            raise ReleaseAssetError("expected package asset is oversized")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                size += len(chunk)
                if size > max_bytes:
                    raise ReleaseAssetError("expected package asset is oversized")
                digest.update(chunk)
        return size, digest.hexdigest()
    except OSError as error:
        raise ReleaseAssetError("expected package asset is missing or unreadable") from error


def _metadata_url(repo: str, tag: str) -> str:
    if not _REPO.fullmatch(repo):
        raise ReleaseAssetError("release repository is invalid")
    return f"https://{_API_HOST}/repos/{repo}/releases/tags/{tag}"


def _find_authenticated_draft(
    client: httpx.Client,
    repo: str,
    tag: str,
    *,
    headers: Mapping[str, str],
    policy: DownloadPolicy,
    expected_release_id: int | None = None,
) -> Mapping[str, object] | None:
    """Find one exact draft hidden from GitHub's release-by-tag endpoint."""
    matches: list[Mapping[str, object]] = []
    expected_match: Mapping[str, object] | None = None
    for page in range(1, 11):
        url = f"https://{_API_HOST}/repos/{repo}/releases?per_page=100&page={page}"
        with open_validated_stream(client, url, headers=headers, policy=policy) as response:
            if response.status_code != httpx.codes.OK:
                raise ReleaseAssetError(
                    f"release inventory API returned HTTP {response.status_code}"
                )
            try:
                parsed = json.loads(
                    _read_bounded(
                        response, max_bytes=MAX_METADATA_BYTES, max_seconds=_METADATA_SECONDS
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ReleaseAssetError("release inventory is invalid JSON") from error
        if not isinstance(parsed, list) or len(parsed) > 100:
            raise ReleaseAssetError("release inventory has an invalid shape")
        for item in parsed:
            if not isinstance(item, dict) or type(item.get("tag_name")) is not str:
                raise ReleaseAssetError("release inventory has an invalid shape")
            if item["tag_name"] == tag:
                try:
                    item_id = validate_release_id(item.get("id"))
                except ReleaseIdentityError as error:
                    raise ReleaseAssetError(str(error)) from error
                if item.get("draft") is not True:
                    if expected_release_id != item_id:
                        raise ReleaseAssetError("release inventory contains a duplicate exact tag")
                    continue
                if expected_release_id is not None:
                    if item_id != expected_release_id or expected_match is not None:
                        raise ReleaseAssetError(
                            "release inventory contains duplicate matching drafts"
                        )
                    expected_match = item
                else:
                    if item_id in {match.get("id") for match in matches}:
                        raise ReleaseAssetError(
                            "release inventory contains duplicate matching drafts"
                        )
                    matches.append(item)
        if len(matches) > 1:
            raise ReleaseAssetError("release inventory contains duplicate matching drafts")
        if len(parsed) < 100:
            if expected_release_id is not None:
                if expected_match is None:
                    raise ReleaseAssetError("release inventory does not contain the expected draft")
                return expected_match
            return matches[0] if matches else None
    raise ReleaseAssetError("release inventory exceeds the ten-page search bound")


def fetch_existing_release(
    repo: str,
    tag: str,
    destination: Path,
    *,
    token: str,
    expected_dir: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ExistingRelease | None:
    """Download precisely one verified GitHub release, or return ``None`` for 404."""
    if not token:
        raise ReleaseAssetError("GitHub token is required")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "orphanet-link-release-verifier",
    }
    metadata_policy = DownloadPolicy(
        allowed_hosts=frozenset({_API_HOST}),
        max_bytes=MAX_METADATA_BYTES,
        max_seconds=_METADATA_SECONDS,
    )
    try:
        with httpx.Client(
            follow_redirects=False, timeout=_METADATA_SECONDS, transport=transport
        ) as client:
            with open_validated_stream(
                client, _metadata_url(repo, tag), headers=headers, policy=metadata_policy
            ) as response:
                if response.status_code == httpx.codes.NOT_FOUND:
                    parsed = _find_authenticated_draft(
                        client, repo, tag, headers=headers, policy=metadata_policy
                    )
                    if parsed is None:
                        return None
                if response.status_code != httpx.codes.OK:
                    if response.status_code != httpx.codes.NOT_FOUND:
                        raise ReleaseAssetError(f"release API returned HTTP {response.status_code}")
                else:
                    try:
                        parsed = json.loads(
                            _read_bounded(
                                response,
                                max_bytes=MAX_METADATA_BYTES,
                                max_seconds=_METADATA_SECONDS,
                            ).decode("utf-8")
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise ReleaseAssetError("release metadata is invalid JSON") from error
            release_id, tag_name, target_commitish, is_draft, immutable, assets = _release_assets(
                parsed, repo, tag
            )
            if is_draft:
                _find_authenticated_draft(
                    client,
                    repo,
                    tag,
                    headers=headers,
                    policy=metadata_policy,
                    expected_release_id=release_id,
                )
            complete = len(assets) == len(RELEASE_ASSETS)
            if not complete and expected_dir is None:
                raise ReleaseAssetError("partial draft requires an expected package")
            if destination.exists():
                raise ReleaseAssetError("release destination already exists")
            destination.mkdir(mode=0o700)
            for asset in assets:
                name = asset["name"]
                assert isinstance(name, str)
                url, size, expected_digest = _asset_facts(asset, repo)
                if expected_dir is not None:
                    local_size, local_digest = _local_asset_facts(expected_dir, name)
                    if (size, expected_digest) != (local_size, local_digest):
                        raise ReleaseAssetError(f"existing asset {name} does not match package")
                max_bytes = MAX_ASSET_BYTES if name == ASSET_NAME else MAX_METADATA_BYTES
                policy = DownloadPolicy(
                    allowed_hosts=_ASSET_HOSTS,
                    max_bytes=max_bytes,
                    max_seconds=_ASSET_SECONDS,
                )
                binary_headers = {**headers, "Accept": "application/octet-stream"}
                with open_validated_stream(
                    client, url, headers=binary_headers, policy=policy
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        raise ReleaseAssetError(
                            f"release asset {name} returned HTTP {response.status_code}"
                        )
                    hasher = hashlib.sha256()
                    stream_atomic(
                        response,
                        destination / name,
                        max_bytes=max_bytes,
                        expected_size=size,
                        hasher=hasher,
                        max_seconds=_ASSET_SECONDS,
                    )
                    if hasher.hexdigest() != expected_digest:
                        raise ReleaseAssetError(
                            f"release asset {name} digest does not match metadata"
                        )
            if not is_draft:
                _find_authenticated_draft(
                    client,
                    repo,
                    tag,
                    headers=headers,
                    policy=metadata_policy,
                    expected_release_id=release_id,
                )
    except DownloadError as error:
        raise ReleaseAssetError(str(error)) from error
    except httpx.HTTPError as error:
        raise ReleaseAssetError("release retrieval failed") from error
    except Exception as error:
        if isinstance(error, ReleaseAssetError):
            raise
        raise ReleaseAssetError("release retrieval failed") from error
    return ExistingRelease(
        is_draft=is_draft,
        release_id=release_id,
        tag_name=tag_name,
        target_commitish=target_commitish,
        immutable=immutable,
        complete=complete,
    )


def main() -> int:
    """Fetch the exact remote asset set for the workflow and print its state."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("tag")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--expected-dir", type=Path)
    args = parser.parse_args()
    result = fetch_existing_release(
        args.repo,
        args.tag,
        args.destination,
        token=os.environ.get("GH_TOKEN", ""),
        expected_dir=args.expected_dir,
    )
    print(  # noqa: T201
        json.dumps(
            {"state": "absent"}
            if result is None
            else {
                "state": (
                    "draft_partial"
                    if result.is_draft and not result.complete
                    else "draft"
                    if result.is_draft
                    else "published"
                ),
                "release_id": result.release_id,
                "tag_name": result.tag_name,
                "target_commitish": result.target_commitish,
                "immutable": result.immutable,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
