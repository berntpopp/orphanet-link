"""Bounded identity checks for immutable Orphanet data releases."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

MAX_METADATA_BYTES = 1 << 20
MAX_ASSET_BYTES = 4 * 1024**3
MAX_RELEASE_ID = (1 << 63) - 1
ASSET_NAME = "orphanet.sqlite.gz"
CHECKSUM_NAME = f"{ASSET_NAME}.sha256"
MANIFEST_NAME = "manifest.json"
RELEASE_ASSETS = frozenset({ASSET_NAME, CHECKSUM_NAME, MANIFEST_NAME})
_VERSION_TAG = re.compile(r"^data-[0-9A-Za-z][0-9A-Za-z.-]*$")
_AUDITED_VERSION = "1.3.42 / 4.1.8 [2025-03-03]"
_AUDITED_ORPHANET_DATE = "2026-06-23 07:53:50"
_COUNT_FIELDS = (
    "disorder_count",
    "xref_count",
    "gene_count",
    "phenotype_count",
    "prevalence_count",
)
_MANIFEST_FIELDS = frozenset(
    {"version", "orphanet_date", "schema_version", *_COUNT_FIELDS, "asset"}
)
_OPTIONAL_MANIFEST_FIELDS = frozenset({"build_utc"})

ReleaseState = Literal["create", "published_noop", "draft_publish_existing", "collision"]


class ReleaseIdentityError(ValueError):
    """A release cannot be treated as an exact immutable identity."""


def validate_release_id(value: object) -> int:
    """Return a GitHub ID within the bounded signed-64-bit API range."""
    if type(value) is not int or not 0 < value <= MAX_RELEASE_ID:
        raise ReleaseIdentityError("release ID is outside the safe bound")
    return value


@dataclass(frozen=True)
class ReleaseIdentity:
    """Stable source, asset, schema, and count identity for one release."""

    tag: str
    version: str
    orphanet_date: str
    schema_version: int
    asset: str
    bundle_sha256: str
    bundle_size: int
    counts: tuple[tuple[str, int], ...]


def _read_metadata(path: Path) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ReleaseIdentityError("exact release assets are required") from error
    if not path.is_file() or path.is_symlink() or info.st_size > MAX_METADATA_BYTES:
        raise ReleaseIdentityError("exact release assets are required")
    try:
        value = path.read_bytes()
    except OSError as error:
        raise ReleaseIdentityError("exact release assets are required") from error
    if len(value) > MAX_METADATA_BYTES:
        raise ReleaseIdentityError("release metadata exceeds the 1 MiB bound")
    return value


def _hash_asset(path: Path) -> tuple[str, int]:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ReleaseIdentityError("exact release assets are required") from error
    if not path.is_file() or path.is_symlink() or info.st_size > MAX_ASSET_BYTES:
        raise ReleaseIdentityError("release asset is missing, unsafe, or oversized")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise ReleaseIdentityError("release asset exceeds the size bound")
                digest.update(chunk)
    except OSError as error:
        raise ReleaseIdentityError("release asset is missing or unreadable") from error
    return digest.hexdigest(), size


def _manifest(value: bytes) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ReleaseIdentityError("manifest.json is invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ReleaseIdentityError("manifest.json must be an object")
    return _validate_manifest(parsed)


def _validate_manifest(parsed: Mapping[str, object]) -> Mapping[str, object]:
    """Validate the stable manifest shape whether it came from JSON or a mapping."""
    keys = set(parsed)
    if keys - (_MANIFEST_FIELDS | _OPTIONAL_MANIFEST_FIELDS) or not keys >= _MANIFEST_FIELDS:
        raise ReleaseIdentityError("manifest.json has an incomplete or unexpected shape")
    for key in ("version", "orphanet_date", "asset"):
        if type(parsed[key]) is not str or not parsed[key]:
            raise ReleaseIdentityError(f"manifest.json has an invalid {key}")
    if parsed["asset"] != ASSET_NAME:
        raise ReleaseIdentityError("manifest.json names an unexpected asset")
    if type(parsed["schema_version"]) is not int or parsed["schema_version"] < 1:
        raise ReleaseIdentityError("manifest.json has an invalid schema_version")
    for key in _COUNT_FIELDS:
        count = parsed[key]
        if type(count) is not int or count < 0:
            raise ReleaseIdentityError(f"manifest.json has an invalid {key}")
    if "build_utc" in parsed and (type(parsed["build_utc"]) is not str or not parsed["build_utc"]):
        raise ReleaseIdentityError("manifest.json has an invalid build_utc")
    return parsed


def manifest_identity(value: bytes) -> tuple[tuple[str, object], ...]:
    """Return only the identity-bearing manifest fields, dropping run provenance.

    ``build_utc`` is declared optional by ``_OPTIONAL_MANIFEST_FIELDS`` precisely
    because it records *when* a build ran, not *what* it contains. Two manifests
    that agree here describe the same release even though their bytes differ, so
    this is the only sound way to compare a rebuilt manifest against a stored one.
    """
    parsed = _manifest(value)
    return tuple((key, parsed[key]) for key in sorted(_MANIFEST_FIELDS))


def _checksum(value: bytes, digest: str) -> None:
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReleaseIdentityError("checksum asset is not ASCII") from error
    lines = text.splitlines()
    if len(lines) != 1:
        raise ReleaseIdentityError("checksum asset must contain exactly one line")
    parts = lines[0].split("  ")
    if len(parts) != 2 or parts[1] != ASSET_NAME or parts[0] != digest:
        raise ReleaseIdentityError("checksum asset does not match the release asset")
    if len(parts[0]) != 64 or any(char not in "0123456789abcdef" for char in parts[0]):
        raise ReleaseIdentityError("checksum asset contains an invalid digest")


def read_release_identity(release_dir: Path, tag: str) -> ReleaseIdentity:
    """Read and verify exactly three release assets with bounded metadata."""
    if not _VERSION_TAG.fullmatch(tag):
        raise ReleaseIdentityError("release tag is not a valid data tag")
    if not release_dir.is_dir() or release_dir.is_symlink():
        raise ReleaseIdentityError("release directory is missing or unsafe")
    try:
        names = {path.name for path in release_dir.iterdir()}
    except OSError as error:
        raise ReleaseIdentityError("exact release assets are required") from error
    if names != RELEASE_ASSETS:
        raise ReleaseIdentityError("exact release assets are required")
    manifest = _manifest(_read_metadata(release_dir / MANIFEST_NAME))
    digest, size = _hash_asset(release_dir / ASSET_NAME)
    _checksum(_read_metadata(release_dir / CHECKSUM_NAME), digest)
    version = str(manifest["version"])
    if not _tag_matches_manifest(version, str(manifest["orphanet_date"]), tag):
        raise ReleaseIdentityError("manifest version does not match release tag")
    return ReleaseIdentity(
        tag=tag,
        version=version,
        orphanet_date=str(manifest["orphanet_date"]),
        schema_version=cast(int, manifest["schema_version"]),
        asset=ASSET_NAME,
        bundle_sha256=digest,
        bundle_size=size,
        counts=tuple((key, cast(int, manifest[key])) for key in _COUNT_FIELDS),
    )


def release_tag(
    version: str,
    orphanet_date: str,
    *,
    collision_revision: int | None = None,
) -> str:
    """Return a readable tag bound to the upstream dataset revision."""
    slug = re.sub(r"[^0-9A-Za-z.]+", "-", version).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise ReleaseIdentityError("source version cannot produce a release tag")
    try:
        revision = datetime.strptime(orphanet_date, "%Y-%m-%d %H:%M:%S")
    except ValueError as error:
        raise ReleaseIdentityError("manifest has an invalid orphanet_date") from error
    tag = f"data-{slug}-r{revision:%Y%m%dT%H%M%SZ}"
    if collision_revision is None:
        return tag
    if (version, orphanet_date) != (_AUDITED_VERSION, _AUDITED_ORPHANET_DATE):
        raise ReleaseIdentityError("collision revision is only supported for the audited source")
    if type(collision_revision) is not int or collision_revision != 2:
        raise ReleaseIdentityError("collision revision must be exactly revision 2")
    return f"{tag}-r{collision_revision}"


def publication_tag(version: str, orphanet_date: str) -> str:
    """Select the audited collision tag only for the known historical dataset."""
    base = release_tag(version, orphanet_date)
    if (version, orphanet_date) == (_AUDITED_VERSION, _AUDITED_ORPHANET_DATE):
        return release_tag(version, orphanet_date, collision_revision=2)
    return base


def _tag_matches_manifest(version: str, orphanet_date: str, tag: str) -> bool:
    """Accept the base identity or the one audited collision revision."""
    base = release_tag(version, orphanet_date)
    if tag == base:
        return True
    if (version, orphanet_date) != (_AUDITED_VERSION, _AUDITED_ORPHANET_DATE):
        return False
    suffix = tag.removeprefix(f"{base}-r")
    return tag.startswith(f"{base}-r") and suffix == "2"


def classify_release(
    current: Mapping[str, object],
    existing: Mapping[str, object] | None,
    *,
    is_draft: bool,
) -> ReleaseState:
    """Return a typed mutation state, rejecting incomplete or differing identities."""
    current_identity = _mapping_identity(current)
    if existing is None:
        return "create"
    existing_identity = _mapping_identity(existing)
    if current_identity != existing_identity:
        return "collision"
    return "draft_publish_existing" if is_draft else "published_noop"


def _mapping_identity(value: Mapping[str, object]) -> ReleaseIdentity:
    """Reject malformed mapping inputs before they can select a no-op state."""
    required = {"tag", "assets", "bundle_sha256", "bundle_size", "manifest"}
    if set(value) != required:
        raise ReleaseIdentityError("exact release assets have an invalid identity shape")
    tag = value["tag"]
    assets = value["assets"]
    digest = value["bundle_sha256"]
    size = value["bundle_size"]
    manifest = value["manifest"]
    if type(tag) is not str or not _VERSION_TAG.fullmatch(tag):
        raise ReleaseIdentityError("release identity has an invalid tag")
    if (
        not isinstance(assets, list)
        or any(type(name) is not str for name in assets)
        or len(assets) != len(set(assets))
        or set(assets) != RELEASE_ASSETS
    ):
        raise ReleaseIdentityError("release identity has an invalid asset inventory")
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ReleaseIdentityError("release identity has an invalid bundle_sha256")
    if type(size) is not int or size < 0 or size > MAX_ASSET_BYTES:
        raise ReleaseIdentityError("release identity has an invalid bundle_size")
    if not isinstance(manifest, Mapping):
        raise ReleaseIdentityError("release identity has an invalid manifest")
    parsed = _validate_manifest(manifest)
    version = cast(str, parsed["version"])
    if not _tag_matches_manifest(version, cast(str, parsed["orphanet_date"]), tag):
        raise ReleaseIdentityError("release identity manifest version does not match tag")
    return ReleaseIdentity(
        tag=tag,
        version=version,
        orphanet_date=cast(str, parsed["orphanet_date"]),
        schema_version=cast(int, parsed["schema_version"]),
        asset=ASSET_NAME,
        bundle_sha256=digest,
        bundle_size=size,
        counts=tuple((key, cast(int, parsed[key])) for key in _COUNT_FIELDS),
    )


def compare_release_directories(
    current_dir: Path,
    existing_dir: Path,
    tag: str,
    *,
    is_draft: bool,
) -> ReleaseState:
    """Verify both exact asset directories, then classify their identity."""
    current = read_release_identity(current_dir, tag)
    existing = read_release_identity(existing_dir, tag)
    if current != existing:
        return "collision"
    return "draft_publish_existing" if is_draft else "published_noop"


def verify_release_identity(
    current_dir: Path,
    existing_dir: Path,
    tag: str,
    *,
    is_draft: bool,
) -> ReleaseState:
    """Verify an existing release before any release mutation is permitted."""
    return compare_release_directories(current_dir, existing_dir, tag, is_draft=is_draft)
