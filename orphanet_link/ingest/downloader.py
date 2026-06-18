"""Conditional download of Orphadata XML product files.

Orphadata serves static XML files on stable URLs that honour ``ETag`` /
``Last-Modified``.  We cache the last-seen validators per URL in a
``download_cache.json`` sidecar and issue conditional ``GET`` requests, so a
re-download only transfers a body when the upstream file actually changed (a
weekly cron check is then almost always a cheap ``304``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from orphanet_link.exceptions import DownloadError

if TYPE_CHECKING:
    from orphanet_link.config import OrphanetDataConfig

logger = logging.getLogger(__name__)

CACHE_FILENAME = "download_cache.json"
_CHUNK_SIZE = 1 << 16  # 64 KiB


@dataclass
class DownloadResult:
    """Outcome of a conditional download of one Orphadata file."""

    key: str
    path: Path | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    content_length: int | None = None


@dataclass
class BulkDownload:
    """Outcome of downloading a set of Orphadata files together."""

    results: dict[str, DownloadResult] = field(default_factory=dict)

    @property
    def not_modified(self) -> bool:
        """True only when every downloaded file returned 304 (nothing changed)."""
        return bool(self.results) and all(r.not_modified for r in self.results.values())

    @property
    def paths(self) -> dict[str, Path]:
        """Map of key -> local path for files that were downloaded (or already exist)."""
        return {k: r.path for k, r in self.results.items() if r.path is not None}

    def path(self, key: str) -> Path | None:
        """Local path for a download key (``None`` if not downloaded)."""
        res = self.results.get(key)
        return res.path if res is not None else None

    def validators(self) -> dict[str, dict[str, str | None]]:
        """Per-file ``{etag, last_modified}`` for provenance."""
        return {
            key: {"etag": r.etag, "last_modified": r.last_modified}
            for key, r in self.results.items()
        }


def _cache_path(config: OrphanetDataConfig) -> Path:
    return config.data_dir / CACHE_FILENAME


def _read_cache(config: OrphanetDataConfig) -> dict[str, dict[str, str | None]]:
    cache_file = _cache_path(config)
    if not cache_file.exists():
        return {}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(
    config: OrphanetDataConfig,
    url: str,
    *,
    etag: str | None,
    last_modified: str | None,
) -> None:
    cache_file = _cache_path(config)
    data = _read_cache(config)
    data[url] = {"etag": etag, "last_modified": last_modified}
    cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stream_to_file(response: httpx.Response, dest: Path) -> None:
    with dest.open("wb") as handle:
        for chunk in response.iter_bytes(_CHUNK_SIZE):
            handle.write(chunk)


def _build_url(config: OrphanetDataConfig, filename: str) -> str:
    """Resolve ``filename`` against ``config.base_url`` (which always ends in ``/``)."""
    return config.base_url + filename


def download_file(
    config: OrphanetDataConfig,
    key: str,
    filename: str,
    *,
    force: bool = False,
) -> DownloadResult:
    """Conditionally download ``filename`` from Orphadata to ``data_dir/filename``.

    Sends ``If-None-Match`` / ``If-Modified-Since`` from the cache unless
    ``force``.  A ``304`` reuses the existing local file without a body transfer.

    Args:
        config: Data-store configuration (``base_url``, ``data_dir``,
            ``download_timeout``, ``user_agent``).
        key: Logical key for this file (used in the result and logs).
        filename: Bare filename (e.g. ``en_product1.xml``); resolved against
            ``config.base_url``.
        force: Skip conditional headers and always re-download.

    Returns:
        :class:`DownloadResult` with ``.path``, ``.etag``, ``.not_modified``.

    Raises:
        DownloadError: On any HTTP error or network failure.
    """
    config.data_dir.mkdir(parents=True, exist_ok=True)
    url = _build_url(config, filename)
    dest = config.data_dir / filename
    headers: dict[str, str] = {"User-Agent": config.user_agent}

    if not force:
        cached = _read_cache(config).get(url, {})
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = str(cached["last_modified"])

    try:
        with (
            httpx.Client(follow_redirects=True, timeout=config.download_timeout) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            if response.status_code == httpx.codes.NOT_MODIFIED:
                logger.debug("not_modified key=%s url=%s", key, url)
                return DownloadResult(
                    key=key,
                    path=dest if dest.exists() else None,
                    etag=headers.get("If-None-Match"),
                    last_modified=headers.get("If-Modified-Since"),
                    not_modified=True,
                )
            response.raise_for_status()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = _int_or_none(response.headers.get("Content-Length"))
            _stream_to_file(response, dest)
    except httpx.HTTPStatusError as exc:
        raise DownloadError(f"GET {url} failed: {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"GET {url} failed: {exc}") from exc

    _write_cache(config, url, etag=etag, last_modified=last_modified)
    logger.info(
        "downloaded key=%s filename=%s bytes=%s etag=%s",
        key,
        filename,
        content_length,
        etag,
    )
    return DownloadResult(
        key=key,
        path=dest,
        etag=etag,
        last_modified=last_modified,
        not_modified=False,
        content_length=content_length,
    )


def download_files(
    config: OrphanetDataConfig,
    files: dict[str, str],
    optional: set[str] | None = None,
    *,
    force: bool = False,
) -> BulkDownload:
    """Download a set of Orphadata files conditionally (unless ``force``).

    Args:
        config: Data-store configuration.
        files: Map of ``key -> filename`` to download.  Filenames are resolved
            against ``config.base_url``.
        optional: Keys whose download failure degrades gracefully (the existing
            local file is kept if present; no exception is raised).  Required
            files (not in ``optional``) raise :class:`DownloadError` on failure.
        force: Skip conditional headers and always re-download.

    Returns:
        :class:`BulkDownload` with ``.paths`` and ``.not_modified``.
    """
    optional_keys: set[str] = optional or set()
    bulk = BulkDownload()

    for key, filename in files.items():
        try:
            bulk.results[key] = download_file(config, key, filename, force=force)
        except DownloadError:
            if key not in optional_keys:
                raise
            dest = config.data_dir / filename
            logger.warning("optional_file_unavailable key=%s filename=%s", key, filename)
            bulk.results[key] = DownloadResult(
                key=key,
                path=dest if dest.exists() else None,
                not_modified=True,
            )

    return bulk
