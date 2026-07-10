"""Runtime data resolver for the orphanet-link SQLite index.

Three public entry points:

* :func:`fetch_prebuilt` — download the prebuilt DB from a GitHub Release.
* :func:`local_build`    — download Orphadata XML and build locally.
* :func:`ensure_database` — orchestrate the two above with a validity check.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

import httpx

from orphanet_link.constants import SCHEMA_VERSION
from orphanet_link.exceptions import DataUnavailableError, DownloadError
from orphanet_link.ingest.download_security import (
    DownloadPolicy,
    copy_bounded,
    open_validated_stream,
    stream_atomic,
)

if TYPE_CHECKING:
    from orphanet_link.config import OrphanetDataConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"
_ASSET_GZ = "orphanet.sqlite.gz"
_ASSET_SHA = "orphanet.sqlite.gz.sha256"
_ASSET_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com"})
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _release_url(config: OrphanetDataConfig) -> str:
    base = f"{_GH_API}/repos/{config.release_repo}/releases"
    if config.release_tag == "latest":
        return f"{base}/latest"
    return f"{base}/tags/{config.release_tag}"


def _find_asset(assets: list[dict[str, Any]], name: str) -> str:
    """Return the browser_download_url for *name*, or raise DataUnavailableError."""
    for asset in assets:
        if asset.get("name") == name:
            url: str = asset.get("browser_download_url", "")
            if url:
                return url
    raise DataUnavailableError(f"Release asset '{name}' not found in GitHub Release.")


def _read_bounded(response: httpx.Response, *, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise DownloadError(f"download exceeded {max_bytes} bytes")
        except ValueError:
            pass
    data = bytearray()
    for chunk in response.iter_bytes(min(1 << 16, max_bytes + 1)):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise DownloadError(f"download exceeded {max_bytes} bytes")
    return bytes(data)


def _fetch_release(config: OrphanetDataConfig, release_url: str) -> dict[str, Any]:
    headers = {"User-Agent": config.user_agent, "Accept": "application/vnd.github+json"}
    try:
        with (
            httpx.Client(follow_redirects=False, timeout=config.download_timeout) as client,
            client.stream("GET", release_url, headers=headers) as response,
        ):
            response.raise_for_status()
            release = json.loads(
                _read_bounded(response, max_bytes=config.max_metadata_bytes).decode("utf-8")
            )
    except httpx.HTTPStatusError as exc:
        raise DataUnavailableError(
            f"GitHub Releases API returned HTTP {exc.response.status_code}: {release_url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DataUnavailableError(f"Network error fetching release metadata: {exc}") from exc
    except (DownloadError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataUnavailableError(f"Invalid GitHub release metadata: {exc}") from exc
    if not isinstance(release, dict):
        raise DataUnavailableError("Invalid GitHub release metadata: expected an object.")
    return release


def _asset_policy(config: OrphanetDataConfig, *, max_bytes: int) -> DownloadPolicy:
    return DownloadPolicy(
        allowed_hosts=_ASSET_HOSTS,
        max_bytes=max_bytes,
        max_seconds=config.max_download_seconds,
    )


def _download_asset(
    url: str,
    destination: Path,
    config: OrphanetDataConfig,
    *,
    max_bytes: int,
    hasher: Any | None = None,
) -> None:
    headers = {"User-Agent": config.user_agent, "Accept": "application/octet-stream"}
    policy = _asset_policy(config, max_bytes=max_bytes)
    try:
        with (
            httpx.Client(follow_redirects=False, timeout=config.download_timeout) as client,
            open_validated_stream(client, url, headers=headers, policy=policy) as response,
        ):
            response.raise_for_status()
            stream_atomic(
                response,
                destination,
                max_bytes=policy.max_bytes,
                hasher=hasher,
                max_seconds=policy.max_seconds,
            )
    except httpx.HTTPStatusError as exc:
        raise DataUnavailableError(f"HTTP {exc.response.status_code} fetching {url}") from exc
    except httpx.HTTPError as exc:
        raise DataUnavailableError(f"Network error fetching {url}: {exc}") from exc
    except DownloadError as exc:
        raise DataUnavailableError(str(exc)) from exc


def _download_sidecar(url: str, config: OrphanetDataConfig) -> bytes:
    headers = {"User-Agent": config.user_agent, "Accept": "application/octet-stream"}
    policy = _asset_policy(config, max_bytes=config.max_metadata_bytes)
    try:
        with (
            httpx.Client(follow_redirects=False, timeout=config.download_timeout) as client,
            open_validated_stream(client, url, headers=headers, policy=policy) as response,
        ):
            response.raise_for_status()
            return _read_bounded(response, max_bytes=config.max_metadata_bytes)
    except httpx.HTTPStatusError as exc:
        raise DataUnavailableError(f"HTTP {exc.response.status_code} fetching {url}") from exc
    except httpx.HTTPError as exc:
        raise DataUnavailableError(f"Network error fetching {url}: {exc}") from exc
    except DownloadError as exc:
        raise DataUnavailableError(str(exc)) from exc


def _check_schema(db_path: Path) -> None:
    """Raise DataUnavailableError if meta.schema_version != SCHEMA_VERSION."""
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT schema_version FROM meta WHERE id=1").fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        raise DataUnavailableError(f"Cannot read meta table from {db_path}: {exc}") from exc
    if row is None:
        raise DataUnavailableError("meta table is empty; cannot verify schema version.")
    version = row[0]
    if version != SCHEMA_VERSION:
        raise DataUnavailableError(
            f"Schema version mismatch: DB has {version}, expected {SCHEMA_VERSION}."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_prebuilt(config: OrphanetDataConfig) -> Path:
    """Download the prebuilt DB from a GitHub Release and place it at config.db_path.

    Steps:
      1. Resolve the release via the GitHub REST API.
      2. Download ``orphanet.sqlite.gz`` and ``orphanet.sqlite.gz.sha256``.
      3. Verify the SHA-256 digest.
      4. Gunzip to ``config.db_path``.
      5. Open the DB read-only and check ``meta.schema_version == SCHEMA_VERSION``.

    Returns:
        ``config.db_path`` on success.

    Raises:
        DataUnavailableError: On any HTTP, asset, sha, or schema error.
    """
    release_url = _release_url(config)
    logger.debug("fetch_prebuilt release_url=%s", release_url)

    release = _fetch_release(config, release_url)

    assets: list[dict[str, Any]] = release.get("assets", [])
    gz_url = _find_asset(assets, _ASSET_GZ)
    sha_url = _find_asset(assets, _ASSET_SHA)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = config.db_path
    gz_fd, gz_name = tempfile.mkstemp(dir=config.data_dir, suffix=".gz.tmp")
    os.close(gz_fd)
    gz_path = Path(gz_name)
    db_fd, db_name = tempfile.mkstemp(dir=config.data_dir, suffix=".sqlite.tmp")
    os.close(db_fd)
    db_path_tmp = Path(db_name)
    digest = hashlib.sha256()
    try:
        logger.info("fetch_prebuilt downloading gz asset url=%s", gz_url)
        _download_asset(
            gz_url,
            gz_path,
            config,
            max_bytes=config.max_bundle_bytes,
            hasher=digest,
        )
        logger.debug("fetch_prebuilt downloading sha256 asset url=%s", sha_url)
        sha_bytes = _download_sidecar(sha_url, config)
        # The sidecar may be "hexdigest  filename\n" or just "hexdigest\n".
        try:
            expected_hex = sha_bytes.decode("ascii").split()[0]
        except (UnicodeDecodeError, IndexError) as exc:
            raise DataUnavailableError("Invalid SHA-256 sidecar.") from exc
        if _SHA256_RE.fullmatch(expected_hex) is None:
            raise DataUnavailableError(
                "Invalid SHA-256 sidecar: expected exactly 64 hex characters."
            )
        actual_hex = digest.hexdigest()
        if actual_hex.lower() != expected_hex.lower():
            raise DataUnavailableError(
                f"SHA-256 mismatch: expected {expected_hex}, got {actual_hex}."
            )
        try:
            with (
                gz_path.open("rb") as compressed,
                gzip.GzipFile(fileobj=compressed, mode="rb") as expanded,
                db_path_tmp.open("wb") as destination,
            ):
                copy_bounded(
                    cast(BinaryIO, expanded),
                    destination,
                    max_bytes=config.max_database_bytes,
                )
        except (OSError, DownloadError) as exc:
            raise DataUnavailableError(f"Failed to decompress prebuilt DB: {exc}") from exc
        _check_schema(db_path_tmp)
        os.replace(db_path_tmp, db_path)
    finally:
        gz_path.unlink(missing_ok=True)
        db_path_tmp.unlink(missing_ok=True)
    logger.info("fetch_prebuilt wrote db db_file=%s", db_path.name)
    return db_path


def local_build(config: OrphanetDataConfig) -> Path:
    """Download Orphadata XML files and build the SQLite index locally.

    Returns:
        ``config.db_path`` on success.

    Raises:
        DownloadError: If a required Orphadata file cannot be downloaded.
        BuildError: If the ingest builder fails.
    """
    from orphanet_link.exceptions import DownloadError
    from orphanet_link.ingest.builder import build_database
    from orphanet_link.ingest.downloader import download_files
    from orphanet_link.ingest.specialties import product3_filenames

    single_products: dict[str, str] = {
        "product1": "en_product1.xml",
        "product4": "en_product4.xml",
        "product6": "en_product6.xml",
        "product7": "en_product7.xml",
        "product9_prev": "en_product9_prev.xml",
        "product9_ages": "en_product9_ages.xml",
        "funct": "en_funct_consequences.xml",
    }

    all_files: dict[str, str] = {}
    all_files.update(single_products)
    for sid, fname in product3_filenames().items():
        all_files[f"product3_{sid}"] = fname

    optional_keys = {k for k in all_files if k.startswith("product3_")}

    logger.info("local_build starting download of %d files", len(all_files))
    try:
        bulk = download_files(config, all_files, optional=optional_keys)
    except DownloadError:
        raise

    paths: dict[str, Path] = {}
    classification_paths: dict[str, Path] = {}
    for key, path in bulk.paths.items():
        if key.startswith("product3_"):
            sid = key[len("product3_") :]
            classification_paths[sid] = path
        else:
            paths[key] = path

    db_path = build_database(config, paths, classification_paths)
    logger.info("local_build complete db_file=%s", db_path.name)
    return db_path


def _db_is_valid(config: OrphanetDataConfig) -> bool:
    """Return True if db_path exists and has the correct schema version."""
    if not config.db_path.exists():
        return False
    try:
        _check_schema(config.db_path)
        return True
    except DataUnavailableError:
        return False


def ensure_database(config: OrphanetDataConfig) -> Path:
    """Return a ready-to-use DB path, building or fetching if necessary.

    Decision tree:
      1. If ``config.db_path`` exists with a valid schema_version, return it.
      2. Else if ``config.prefer_prebuilt``: try :func:`fetch_prebuilt`;
         on failure fall back to :func:`local_build`.
      3. Else call :func:`local_build` directly.

    Returns:
        ``config.db_path``.

    Raises:
        DataUnavailableError | DownloadError | BuildError: if all paths fail.
    """
    if _db_is_valid(config):
        logger.debug("ensure_database db already valid db_file=%s", config.db_path.name)
        return config.db_path

    if config.prefer_prebuilt:
        try:
            logger.info("ensure_database trying fetch_prebuilt")
            return fetch_prebuilt(config)
        except DataUnavailableError as exc:
            logger.warning(
                "ensure_database prebuilt fetch failed, falling back to local_build: %s",
                exc,
            )

    logger.info("ensure_database running local_build")
    return local_build(config)
