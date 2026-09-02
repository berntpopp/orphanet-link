"""Build and verify the GeneFoundry runtime data identity v1 for orphanet-link.

The init sidecar materializes one immutable release bundle into the data volume and
writes :data:`IDENTITY_FILENAME` beside the database. The serving process never trusts
that file on its word: :func:`verify_runtime_identity` rehashes the database bytes and
only then reports the ``(release_tag, digest)`` pair the fleet controller reads from
``/health``.

The digest is ``sha256:<compressed bundle sha256>`` -- the SHA-256 of the released
``orphanet.sqlite.gz`` asset, which is exactly the value ``container-release.json``
declares as ``data.digest`` and the overlay injects as
``ORPHANET_LINK_DATA__BUNDLE_EXPECTED_SHA256``. One number, three places, no derivation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, cast

#: Written by the init sidecar beside the materialized database.
IDENTITY_FILENAME = "data-identity.json"

_MANIFEST_KEYS = frozenset({"schema_version", "release_tag", "bundle_sha256", "database"})
_DATABASE_KEYS = frozenset({"path", "size_bytes", "sha256"})
_RELEASE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MUTABLE_RELEASE_TAGS = frozenset({"latest", "main", "master", "head", "stable", "current"})
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024


class RuntimeDataIdentityError(ValueError):
    """A materialized data root cannot prove its runtime identity."""


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a value as canonical UTF-8 JSON for identity comparison."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def is_immutable_release_tag(value: object) -> bool:
    """True when ``value`` names one immutable data release rather than a moving alias."""
    return (
        isinstance(value, str)
        and _RELEASE_TAG.fullmatch(value) is not None
        and value.lower() not in _MUTABLE_RELEASE_TAGS
    )


def _validated_release_tag(value: object) -> str:
    if not is_immutable_release_tag(value):
        raise RuntimeDataIdentityError("release_tag must be an immutable release identifier")
    return cast(str, value)


def _validated_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise RuntimeDataIdentityError(f"{label} must be exactly 64 lowercase hex characters")
    return value


def _resolved_root(root: Path) -> Path:
    if root.is_symlink():
        raise RuntimeDataIdentityError("materialized data root is a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeDataIdentityError("materialized data root does not exist") from exc
    if not resolved.is_dir():
        raise RuntimeDataIdentityError("materialized data root is not a directory")
    return resolved


def _relative_database_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RuntimeDataIdentityError("database path must be a non-empty POSIX string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or path == PurePosixPath(".")
        or ".." in path.parts
    ):
        raise RuntimeDataIdentityError("database path is not a canonical relative POSIX path")
    if path == PurePosixPath(IDENTITY_FILENAME):
        raise RuntimeDataIdentityError("the identity manifest cannot be the database")
    return path


def _regular_file(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise RuntimeDataIdentityError("database path is a symlink alias")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeDataIdentityError("database file is missing") from exc
    if resolved != candidate or not resolved.is_file():
        raise RuntimeDataIdentityError("database path is not a regular file beneath the data root")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeDataIdentityError("database resolves outside the data root") from exc
    return resolved


def _measure(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeDataIdentityError("database file is unreadable") from exc
    return size, digest.hexdigest()


def build_identity_manifest(
    root: Path, *, release_tag: str, bundle_sha256: str, database: str
) -> dict[str, Any]:
    """Measure the materialized database and return the exact v1 identity manifest."""
    resolved_root = _resolved_root(root)
    tag = _validated_release_tag(release_tag)
    bundle = _validated_sha256(bundle_sha256.removeprefix("sha256:").lower(), "bundle_sha256")
    relative = _relative_database_path(database)
    size, digest = _measure(_regular_file(resolved_root, relative))
    return {
        "schema_version": 1,
        "release_tag": tag,
        "bundle_sha256": bundle,
        "database": {"path": relative.as_posix(), "size_bytes": size, "sha256": digest},
    }


def write_identity_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    """Write the identity manifest atomically beside the materialized database."""
    resolved_root = _resolved_root(root)
    target = resolved_root / IDENTITY_FILENAME
    temporary = resolved_root / f".{IDENTITY_FILENAME}.tmp"
    payload = canonical_json_bytes(manifest)
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeDataIdentityError("identity manifest could not be written") from exc
    return target


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / IDENTITY_FILENAME
    if path.is_symlink():
        raise RuntimeDataIdentityError("identity manifest must not be a symlink")
    if not path.is_file():
        raise RuntimeDataIdentityError("identity manifest is missing or is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeDataIdentityError("identity manifest is unreadable or invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise RuntimeDataIdentityError("identity manifest has invalid keys")
    if value["schema_version"] != 1 or not isinstance(value["schema_version"], int):
        raise RuntimeDataIdentityError("identity manifest schema_version must be integer 1")
    database = value["database"]
    if not isinstance(database, dict) or set(database) != _DATABASE_KEYS:
        raise RuntimeDataIdentityError("identity manifest database entry has invalid keys")
    return cast(dict[str, Any], value)


def verify_runtime_identity(root: Path, *, database: str) -> dict[str, str]:
    """Rehash the materialized database and return its proven release_tag/digest.

    The manifest is re-read after the content pass so an identity file rewritten while
    the database was being hashed cannot be accepted; a portable filesystem offers no
    atomic directory-plus-content snapshot, so mutation after the final read stays
    outside this v1 guarantee.
    """
    resolved_root = _resolved_root(root)
    manifest = _load_manifest(resolved_root)
    release_tag = _validated_release_tag(manifest["release_tag"])
    bundle = _validated_sha256(manifest["bundle_sha256"], "bundle_sha256")
    entry = manifest["database"]
    relative = _relative_database_path(entry["path"])
    if relative.as_posix() != database:
        raise RuntimeDataIdentityError("identity manifest describes a different database file")
    expected_size = entry["size_bytes"]
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise RuntimeDataIdentityError("database size_bytes must be a non-negative integer")
    expected_digest = _validated_sha256(entry["sha256"], "database sha256")

    size, digest = _measure(_regular_file(resolved_root, relative))
    if size != expected_size or digest != expected_digest:
        raise RuntimeDataIdentityError("materialized database does not match its identity manifest")
    if canonical_json_bytes(_load_manifest(resolved_root)) != canonical_json_bytes(manifest):
        raise RuntimeDataIdentityError("identity manifest changed during verification")
    return {"release_tag": release_tag, "digest": f"sha256:{bundle}"}
