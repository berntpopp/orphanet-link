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


def _release_assets(value: object) -> tuple[bool, tuple[Mapping[str, object], ...]]:
    if not isinstance(value, dict) or type(value.get("draft")) is not bool:
        raise ReleaseAssetError("release metadata has an invalid shape")
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise ReleaseAssetError("release metadata has an invalid asset inventory")
    by_name: dict[str, Mapping[str, object]] = {}
    asset_ids: set[int] = set()
    for asset in assets:
        if (
            not isinstance(asset, dict)
            or type(asset.get("name")) is not str
            or type(asset.get("id")) is not int
            or asset["id"] <= 0
            or asset["id"] in asset_ids
        ):
            raise ReleaseAssetError("release metadata has an invalid asset inventory")
        name = asset["name"]
        if name in by_name:
            raise ReleaseAssetError("release metadata has a duplicate asset")
        by_name[name] = asset
        asset_ids.add(asset["id"])
    if set(by_name) != RELEASE_ASSETS:
        raise ReleaseAssetError("release metadata has an inexact asset inventory")
    return value["draft"], tuple(by_name[name] for name in sorted(RELEASE_ASSETS))


def _asset_facts(asset: Mapping[str, object], repo: str) -> tuple[str, int, str]:
    identifier = asset.get("id")
    url = asset.get("url")
    size = asset.get("size")
    digest = asset.get("digest")
    expected_url = f"https://{_API_HOST}/repos/{repo}/releases/assets/{identifier}"
    if type(url) is not str or url != expected_url:
        raise ReleaseAssetError("release asset URL is not bound to its API asset ID")
    if (
        type(identifier) is not int
        or identifier <= 0
        or type(size) is not int
        or not isinstance(digest, str)
    ):
        raise ReleaseAssetError("release metadata has an invalid asset")
    match = _DIGEST.fullmatch(digest)
    if (
        match is None
        or size < 0
        or size > (MAX_METADATA_BYTES if asset["name"] != ASSET_NAME else MAX_ASSET_BYTES)
    ):
        raise ReleaseAssetError("release metadata has an invalid asset")
    return url, size, match.group(1)


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
) -> Mapping[str, object] | None:
    """Find one exact draft hidden from GitHub's release-by-tag endpoint."""
    matches: list[Mapping[str, object]] = []
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
                if type(item.get("id")) is not int or item["id"] <= 0:
                    raise ReleaseAssetError("release inventory has an invalid release ID")
                if item.get("draft") is not True:
                    raise ReleaseAssetError("release-by-tag lookup omitted a non-draft release")
                matches.append(item)
        if len(matches) > 1:
            raise ReleaseAssetError("release inventory contains duplicate matching drafts")
        if len(parsed) < 100:
            return matches[0] if matches else None
    raise ReleaseAssetError("release inventory exceeds the ten-page search bound")


def fetch_existing_release(
    repo: str,
    tag: str,
    destination: Path,
    *,
    token: str,
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
            is_draft, assets = _release_assets(parsed)
            if destination.exists():
                raise ReleaseAssetError("release destination already exists")
            destination.mkdir(mode=0o700)
            for asset in assets:
                name = asset["name"]
                assert isinstance(name, str)
                url, size, expected_digest = _asset_facts(asset, repo)
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
    except DownloadError as error:
        raise ReleaseAssetError(str(error)) from error
    except httpx.HTTPError as error:
        raise ReleaseAssetError("release retrieval failed") from error
    except Exception as error:
        if isinstance(error, ReleaseAssetError):
            raise
        raise ReleaseAssetError("release retrieval failed") from error
    return ExistingRelease(is_draft=is_draft)


def main() -> int:
    """Fetch the exact remote asset set for the workflow and print its state."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("tag")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = fetch_existing_release(
        args.repo, args.tag, args.destination, token=os.environ.get("GH_TOKEN", "")
    )
    print("absent" if result is None else "draft" if result.is_draft else "published")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
