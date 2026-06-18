"""Unit tests for orphanet_link.services.data_resolver."""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.constants import SCHEMA_VERSION
from orphanet_link.exceptions import DataUnavailableError
from orphanet_link.services.data_resolver import (
    ensure_database,
    fetch_prebuilt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "berntpopp/orphanet-link"
_GH_LATEST = f"https://api.github.com/repos/{_REPO}/releases/latest"
_GZ_URL = "https://example.com/orphanet.sqlite.gz"
_SHA_URL = "https://example.com/orphanet.sqlite.gz.sha256"


def _make_tiny_db(tmp_path: Path, *, schema_version: int = SCHEMA_VERSION) -> Path:
    """Create a minimal SQLite with a meta row and return its path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "tiny.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE meta ("
        "id INTEGER PRIMARY KEY, schema_version INTEGER, "
        "orphanet_version TEXT, orphanet_date TEXT, "
        "sources TEXT, disorder_count INTEGER, xref_count INTEGER, "
        "gene_count INTEGER, phenotype_count INTEGER, "
        "prevalence_count INTEGER, closure_count INTEGER, "
        "build_utc TEXT, build_duration_s REAL"
        ")"
    )
    conn.execute(
        "INSERT INTO meta VALUES (1,?,NULL,NULL,NULL,0,0,0,0,0,0,NULL,NULL)",
        (schema_version,),
    )
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.commit()
    conn.close()
    return db_path


def _gz_and_sha(db_path: Path) -> tuple[bytes, str]:
    """Return (gzip-compressed bytes, hex sha256 of those bytes)."""
    raw = db_path.read_bytes()
    gz = gzip.compress(raw)
    sha = hashlib.sha256(gz).hexdigest()
    return gz, sha


def _release_json(gz_url: str, sha_url: str) -> dict:
    return {
        "tag_name": "data-1",
        "assets": [
            {"name": "orphanet.sqlite.gz", "browser_download_url": gz_url},
            {"name": "orphanet.sqlite.gz.sha256", "browser_download_url": sha_url},
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(tmp_path: Path) -> OrphanetDataConfig:
    return OrphanetDataConfig(
        data_dir=tmp_path,
        release_repo=_REPO,
        release_tag="latest",
    )


# ---------------------------------------------------------------------------
# fetch_prebuilt — happy path
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_downloads_and_verifies(
    config: OrphanetDataConfig, tmp_path: Path
) -> None:
    """fetch_prebuilt places the DB, verifies SHA-256, and checks schema."""
    tiny_db = _make_tiny_db(tmp_path)
    gz_bytes, sha_hex = _gz_and_sha(tiny_db)

    respx.get(_GH_LATEST).mock(
        return_value=httpx.Response(200, json=_release_json(_GZ_URL, _SHA_URL))
    )
    respx.get(_GZ_URL).mock(return_value=httpx.Response(200, content=gz_bytes))
    respx.get(_SHA_URL).mock(
        return_value=httpx.Response(200, content=sha_hex.encode())
    )

    result = fetch_prebuilt(config)

    assert result == config.db_path
    assert config.db_path.exists()

    # Verify the placed DB is readable and has correct schema.
    conn = sqlite3.connect(config.db_path)
    row = conn.execute("SELECT schema_version FROM meta WHERE id=1").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# fetch_prebuilt — sha256 mismatch
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_sha256_mismatch_raises(
    config: OrphanetDataConfig, tmp_path: Path
) -> None:
    """fetch_prebuilt raises DataUnavailableError on SHA-256 mismatch."""
    tiny_db = _make_tiny_db(tmp_path)
    gz_bytes, _correct_sha = _gz_and_sha(tiny_db)
    wrong_sha = "a" * 64  # definitely wrong

    respx.get(_GH_LATEST).mock(
        return_value=httpx.Response(200, json=_release_json(_GZ_URL, _SHA_URL))
    )
    respx.get(_GZ_URL).mock(return_value=httpx.Response(200, content=gz_bytes))
    respx.get(_SHA_URL).mock(
        return_value=httpx.Response(200, content=wrong_sha.encode())
    )

    with pytest.raises(DataUnavailableError, match="SHA-256 mismatch"):
        fetch_prebuilt(config)


# ---------------------------------------------------------------------------
# fetch_prebuilt — schema_version mismatch
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_schema_version_mismatch_raises(
    config: OrphanetDataConfig, tmp_path: Path
) -> None:
    """fetch_prebuilt raises DataUnavailableError when schema_version is wrong."""
    wrong_version = SCHEMA_VERSION + 99
    tiny_db = _make_tiny_db(tmp_path, schema_version=wrong_version)
    gz_bytes, sha_hex = _gz_and_sha(tiny_db)

    respx.get(_GH_LATEST).mock(
        return_value=httpx.Response(200, json=_release_json(_GZ_URL, _SHA_URL))
    )
    respx.get(_GZ_URL).mock(return_value=httpx.Response(200, content=gz_bytes))
    respx.get(_SHA_URL).mock(
        return_value=httpx.Response(200, content=sha_hex.encode())
    )

    with pytest.raises(DataUnavailableError, match="Schema version mismatch"):
        fetch_prebuilt(config)


# ---------------------------------------------------------------------------
# fetch_prebuilt — 404 release
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_404_release_raises(config: OrphanetDataConfig) -> None:
    """fetch_prebuilt raises DataUnavailableError when the release is not found."""
    respx.get(_GH_LATEST).mock(return_value=httpx.Response(404))

    with pytest.raises(DataUnavailableError):
        fetch_prebuilt(config)


# ---------------------------------------------------------------------------
# fetch_prebuilt — missing asset
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_missing_gz_asset_raises(config: OrphanetDataConfig) -> None:
    """fetch_prebuilt raises DataUnavailableError when the gz asset is absent."""
    release = {
        "tag_name": "data-1",
        "assets": [
            # Only sha256, no gz
            {"name": "orphanet.sqlite.gz.sha256", "browser_download_url": _SHA_URL},
        ],
    }
    respx.get(_GH_LATEST).mock(return_value=httpx.Response(200, json=release))

    with pytest.raises(DataUnavailableError, match=r"orphanet\.sqlite\.gz"):
        fetch_prebuilt(config)


# ---------------------------------------------------------------------------
# ensure_database — valid db already on disk
# ---------------------------------------------------------------------------


def test_ensure_database_returns_existing_valid_db(
    config: OrphanetDataConfig, tmp_path: Path
) -> None:
    """ensure_database returns immediately when a valid DB already exists."""
    # Write a valid DB directly to db_path.
    src = _make_tiny_db(tmp_path / "src")
    config.db_path.write_bytes(src.read_bytes())

    result = ensure_database(config)
    assert result == config.db_path


# ---------------------------------------------------------------------------
# ensure_database — prefer_prebuilt + 404 falls back to local_build
# ---------------------------------------------------------------------------


@respx.mock
def test_ensure_database_prebuilt_404_falls_back_to_local_build(
    config: OrphanetDataConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ensure_database falls back to local_build when fetch_prebuilt fails."""
    assert config.prefer_prebuilt is True  # default

    # Release API returns 404.
    respx.get(_GH_LATEST).mock(return_value=httpx.Response(404))

    dummy_db = _make_tiny_db(tmp_path / "dummy")
    local_build_called = {"count": 0}

    def _fake_local_build(cfg: OrphanetDataConfig) -> Path:
        local_build_called["count"] += 1
        # Place a valid DB at db_path so ensure_database can return it.
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.db_path.write_bytes(dummy_db.read_bytes())
        return cfg.db_path

    monkeypatch.setattr(
        "orphanet_link.services.data_resolver.local_build", _fake_local_build
    )

    result = ensure_database(config)

    assert local_build_called["count"] == 1
    assert result == config.db_path


# ---------------------------------------------------------------------------
# ensure_database — prefer_prebuilt=False goes straight to local_build
# ---------------------------------------------------------------------------


def test_ensure_database_no_prefer_prebuilt_calls_local_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ensure_database skips fetch_prebuilt when prefer_prebuilt is False."""
    config = OrphanetDataConfig(data_dir=tmp_path, prefer_prebuilt=False)
    dummy_db = _make_tiny_db(tmp_path / "dummy")
    calls: list[str] = []

    def _fake_local_build(cfg: OrphanetDataConfig) -> Path:
        calls.append("local_build")
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.db_path.write_bytes(dummy_db.read_bytes())
        return cfg.db_path

    def _fake_fetch_prebuilt(cfg: OrphanetDataConfig) -> Path:  # pragma: no cover
        calls.append("fetch_prebuilt")
        return cfg.db_path

    monkeypatch.setattr(
        "orphanet_link.services.data_resolver.local_build", _fake_local_build
    )
    monkeypatch.setattr(
        "orphanet_link.services.data_resolver.fetch_prebuilt", _fake_fetch_prebuilt
    )

    ensure_database(config)

    assert "local_build" in calls
    assert "fetch_prebuilt" not in calls


# ---------------------------------------------------------------------------
# sha256 file format: "hexdigest  filename" (BSD checksum style)
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_prebuilt_sha256_with_filename_suffix(
    config: OrphanetDataConfig, tmp_path: Path
) -> None:
    """fetch_prebuilt handles sha256 file with '<hash>  filename' format."""
    tiny_db = _make_tiny_db(tmp_path)
    gz_bytes, sha_hex = _gz_and_sha(tiny_db)
    sha_content = f"{sha_hex}  orphanet.sqlite.gz\n".encode()

    respx.get(_GH_LATEST).mock(
        return_value=httpx.Response(200, json=_release_json(_GZ_URL, _SHA_URL))
    )
    respx.get(_GZ_URL).mock(return_value=httpx.Response(200, content=gz_bytes))
    respx.get(_SHA_URL).mock(return_value=httpx.Response(200, content=sha_content))

    result = fetch_prebuilt(config)
    assert result == config.db_path
