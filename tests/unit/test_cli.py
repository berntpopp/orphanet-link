"""Unit tests for the orphanet-link-data CLI (download + build mocked)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.exceptions import DownloadError
from orphanet_link.ingest import cli
from orphanet_link.ingest.downloader import BulkDownload, DownloadResult

FX = Path(__file__).parent.parent / "fixtures"
runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SINGLE_FILENAMES = {
    "product1": "en_product1.xml",
    "product4": "en_product4.xml",
    "product6": "en_product6.xml",
    "product7": "en_product7.xml",
    "product9_prev": "en_product9_prev.xml",
    "product9_ages": "en_product9_ages.xml",
    "funct": "en_funct_consequences.xml",
}


def _fake_bulk(tmp_path: Path, *, not_modified: bool = False) -> BulkDownload:
    """Return a BulkDownload whose paths point to fixture copies in tmp_path."""
    import shutil

    bulk = BulkDownload()
    for key, fname in _SINGLE_FILENAMES.items():
        src = FX / fname
        if src.exists():
            dest = tmp_path / fname
            shutil.copy(src, dest)
            bulk.results[key] = DownloadResult(
                key=key,
                path=dest,
                etag='"fixture"',
                last_modified="Mon, 01 Jun 2026 00:00:00 GMT",
                not_modified=not_modified,
            )
    # Add the one known product3 fixture.
    src3 = FX / "en_product3_156.xml"
    if src3.exists():
        dest3 = tmp_path / "en_product3_156.xml"
        shutil.copy(src3, dest3)
        bulk.results["product3_156"] = DownloadResult(
            key="product3_156",
            path=dest3,
            not_modified=not_modified,
        )
    return bulk


def _make_minimal_db(db_path: Path) -> None:
    """Create a minimal SQLite with a meta row for status tests."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE meta (
            id               INTEGER PRIMARY KEY,
            schema_version   INTEGER,
            orphanet_version TEXT,
            orphanet_date    TEXT,
            source_urls      TEXT,
            disorder_count   INTEGER,
            xref_count       INTEGER,
            gene_count       INTEGER,
            phenotype_count  INTEGER,
            prevalence_count INTEGER,
            closure_count    INTEGER,
            build_utc        TEXT,
            build_duration_s REAL
        )"""
    )
    conn.execute(
        "INSERT INTO meta VALUES (1,1,'1.3.42','2025-12-09','{}',10,5,3,2,1,20,'2026-06-01T00:00:00+00:00',1.5)"
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OrphanetDataConfig:
    config = OrphanetDataConfig(data_dir=tmp_path)
    monkeypatch.setattr(cli, "get_config", lambda: config)
    return config


# ---------------------------------------------------------------------------
# build command
# ---------------------------------------------------------------------------


def test_build_calls_download_and_build(
    cfg: OrphanetDataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bulk = _fake_bulk(tmp_path)
    download_calls: list[tuple] = []
    build_calls: list[tuple] = []

    def fake_download(config, files, optional=None, *, force=False):
        download_calls.append((files, optional, force))
        return bulk

    def fake_build(data_config, paths, classification_paths=None):
        build_calls.append((paths, classification_paths))
        db = data_config.db_path
        _make_minimal_db(db)
        return db

    monkeypatch.setattr(cli, "download_files", fake_download)
    # Patch build_database inside cli's imported namespace.
    import orphanet_link.ingest.builder as builder_mod

    monkeypatch.setattr(builder_mod, "build_database", fake_build)

    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code == 0, result.output
    assert download_calls, "download_files was not called"
    assert build_calls, "build_database was not called"
    # force=True must be passed to download_files on build.
    assert download_calls[0][2] is True


def test_build_prints_meta(
    cfg: OrphanetDataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bulk = _fake_bulk(tmp_path)
    monkeypatch.setattr(cli, "download_files", lambda *a, **kw: bulk)

    import orphanet_link.ingest.builder as builder_mod

    def fake_build(data_config, paths, classification_paths=None):
        db = data_config.db_path
        _make_minimal_db(db)
        return db

    monkeypatch.setattr(builder_mod, "build_database", fake_build)

    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code == 0, result.output
    assert "Built Orphanet database" in result.output
    assert "1.3.42" in result.output


def test_build_exits_1_on_download_error(
    cfg: OrphanetDataConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_download(config, files, optional=None, *, force=False):
        raise DownloadError("connection refused")

    monkeypatch.setattr(cli, "download_files", fail_download)
    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code == 1
    assert "download failed" in result.output.lower()


# ---------------------------------------------------------------------------
# refresh command
# ---------------------------------------------------------------------------


def test_refresh_skips_rebuild_when_not_modified_and_db_exists(
    cfg: OrphanetDataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Create a DB so the "db exists" check passes.
    _make_minimal_db(cfg.db_path)

    bulk = _fake_bulk(tmp_path, not_modified=True)
    download_calls: list[bool] = []
    build_calls: list[int] = []

    def fake_download(config, files, optional=None, *, force=False):
        download_calls.append(force)
        return bulk

    monkeypatch.setattr(cli, "download_files", fake_download)

    import orphanet_link.ingest.builder as builder_mod

    def fake_build(data_config, paths, classification_paths=None):
        build_calls.append(1)
        return data_config.db_path

    monkeypatch.setattr(builder_mod, "build_database", fake_build)

    result = runner.invoke(cli.app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output.lower()
    assert not build_calls, "build_database should NOT have been called"
    # refresh must use force=False.
    assert download_calls == [False]


def test_refresh_rebuilds_when_files_changed(
    cfg: OrphanetDataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bulk = _fake_bulk(tmp_path, not_modified=False)
    build_calls: list[int] = []

    monkeypatch.setattr(cli, "download_files", lambda *a, **kw: bulk)

    import orphanet_link.ingest.builder as builder_mod

    def fake_build(data_config, paths, classification_paths=None):
        build_calls.append(1)
        db = data_config.db_path
        _make_minimal_db(db)
        return db

    monkeypatch.setattr(builder_mod, "build_database", fake_build)

    result = runner.invoke(cli.app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert build_calls, "build_database should have been called"


def test_refresh_rebuilds_when_db_missing_even_if_304(
    cfg: OrphanetDataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the DB doesn't exist yet, always build even on 304 (first-run case)."""
    bulk = _fake_bulk(tmp_path, not_modified=True)
    build_calls: list[int] = []

    monkeypatch.setattr(cli, "download_files", lambda *a, **kw: bulk)

    import orphanet_link.ingest.builder as builder_mod

    def fake_build(data_config, paths, classification_paths=None):
        build_calls.append(1)
        db = data_config.db_path
        _make_minimal_db(db)
        return db

    monkeypatch.setattr(builder_mod, "build_database", fake_build)

    result = runner.invoke(cli.app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert build_calls, "build_database should have been called (no existing DB)"


def test_refresh_exits_1_on_download_error(
    cfg: OrphanetDataConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_download(config, files, optional=None, *, force=False):
        raise DownloadError("timeout")

    monkeypatch.setattr(cli, "download_files", fail_download)
    result = runner.invoke(cli.app, ["refresh"])
    assert result.exit_code == 1
    assert "download failed" in result.output.lower()


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_prints_meta_when_db_exists(cfg: OrphanetDataConfig, tmp_path: Path) -> None:
    _make_minimal_db(cfg.db_path)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "1.3.42" in result.output
    assert "disorders" in result.output.lower()


def test_status_exits_1_when_db_missing(
    cfg: OrphanetDataConfig,
) -> None:
    assert not cfg.db_path.exists()
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
    assert "No Orphanet database" in result.output


# ---------------------------------------------------------------------------
# specialties helpers (imported via cli internals)
# ---------------------------------------------------------------------------


def test_all_files_contains_single_and_product3() -> None:
    files = cli._all_files()
    assert "product1" in files
    assert "product4" in files
    assert "funct" in files
    # At least one product3 entry.
    product3_keys = [k for k in files if k.startswith("product3_")]
    assert len(product3_keys) >= 1


def test_split_paths_separates_correctly(tmp_path: Path) -> None:
    fake_path = tmp_path / "dummy.xml"
    fake_path.touch()

    bulk = BulkDownload()
    bulk.results["product1"] = DownloadResult(key="product1", path=fake_path)
    bulk.results["product3_156"] = DownloadResult(key="product3_156", path=fake_path)

    single, classification = cli._split_paths(bulk)
    assert "product1" in single
    assert "product3_156" not in single
    assert "156" in classification
    assert "product1" not in classification
