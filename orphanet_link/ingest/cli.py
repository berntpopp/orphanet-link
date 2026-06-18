"""Command-line interface for building and refreshing the Orphanet index.

Exposed as the ``orphanet-link-data`` console script and intended as the cron
entry point.  Commands: ``build`` (download + full rebuild), ``refresh``
(conditional rebuild — the cron job), ``fetch`` (download the prebuilt DB from
the GitHub Release), and ``status`` (print provenance of the existing DB).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from orphanet_link.config import get_data_config
from orphanet_link.exceptions import DownloadError
from orphanet_link.ingest.downloader import BulkDownload, download_files
from orphanet_link.ingest.specialties import product3_filenames

if TYPE_CHECKING:
    from orphanet_link.config import OrphanetDataConfig

app = typer.Typer(
    add_completion=False,
    help="Build and refresh the local Orphanet SQLite index from Orphadata XML files.",
)

#: Single-file product keys -> Orphadata filenames (no auth, direct download).
_SINGLE_PRODUCTS: dict[str, str] = {
    "product1": "en_product1.xml",
    "product4": "en_product4.xml",
    "product6": "en_product6.xml",
    "product7": "en_product7.xml",
    "product9_prev": "en_product9_prev.xml",
    "product9_ages": "en_product9_ages.xml",
    "funct": "en_funct_consequences.xml",
}


@dataclass
class _MetaRow:
    """Minimal provenance snapshot read from the ``meta`` table."""

    schema_version: int | None
    orphanet_version: str | None
    orphanet_date: str | None
    disorder_count: int | None
    xref_count: int | None
    gene_count: int | None
    phenotype_count: int | None
    prevalence_count: int | None
    closure_count: int | None
    build_utc: str | None
    build_duration_s: float | None


def _read_meta(db_path: Path) -> _MetaRow | None:
    """Read provenance from the ``meta`` table; return ``None`` if unavailable."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id=1").fetchone()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None
    if row is None:
        return None
    return _MetaRow(
        schema_version=row["schema_version"],
        orphanet_version=row["orphanet_version"],
        orphanet_date=row["orphanet_date"],
        disorder_count=row["disorder_count"],
        xref_count=row["xref_count"],
        gene_count=row["gene_count"],
        phenotype_count=row["phenotype_count"],
        prevalence_count=row["prevalence_count"],
        closure_count=row["closure_count"],
        build_utc=row["build_utc"],
        build_duration_s=row["build_duration_s"],
    )


def _print_meta(meta: _MetaRow, *, header: str) -> None:
    print(header)
    print(f"  schema_version  : {meta.schema_version}")
    print(f"  orphanet_version: {meta.orphanet_version}")
    print(f"  orphanet_date   : {meta.orphanet_date}")
    print(f"  disorders       : {meta.disorder_count}")
    print(f"  xrefs           : {meta.xref_count}")
    print(f"  genes           : {meta.gene_count}")
    print(f"  phenotypes      : {meta.phenotype_count}")
    print(f"  prevalences     : {meta.prevalence_count}")
    print(f"  closure_rows    : {meta.closure_count}")
    print(f"  built_utc       : {meta.build_utc}")
    if meta.build_duration_s is not None:
        print(f"  build_seconds   : {meta.build_duration_s}")


def _all_files() -> dict[str, str]:
    """Combined file map: single products + all product-3 specialty files."""
    combined: dict[str, str] = {}
    combined.update(_SINGLE_PRODUCTS)
    for sid, fname in product3_filenames().items():
        combined[f"product3_{sid}"] = fname
    return combined


def _split_paths(
    bulk: BulkDownload,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Split BulkDownload results into (single_paths, classification_paths)."""
    single: dict[str, Path] = {}
    classification: dict[str, Path] = {}
    for key, path in bulk.paths.items():
        if key.startswith("product3_"):
            sid = key[len("product3_") :]
            classification[sid] = path
        else:
            single[key] = path
    return single, classification


def get_config() -> OrphanetDataConfig:
    """Return the active data-store configuration for the ingest CLI."""
    return get_data_config()


@app.command()
def build() -> None:
    """Force a download and full rebuild of the database."""
    from orphanet_link.ingest.builder import build_database

    config = get_config()
    all_files = _all_files()
    # product3 specialty files may be absent for some IDs — degrade gracefully.
    optional_keys = {k for k in all_files if k.startswith("product3_")}
    try:
        bulk = download_files(config, all_files, optional=optional_keys, force=True)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc

    single_paths, classification_paths = _split_paths(bulk)
    try:
        db_path = build_database(config, single_paths, classification_paths)
    except Exception as exc:
        print(f"ERROR: build failed: {exc}")
        raise typer.Exit(code=1) from exc

    meta = _read_meta(db_path)
    if meta is not None:
        _print_meta(meta, header="Built Orphanet database:")
    else:
        print(f"Built Orphanet database at {db_path}.")


@app.command()
def refresh() -> None:
    """Conditionally refresh the database; rebuild only if any files changed."""
    from orphanet_link.ingest.builder import build_database

    config = get_config()
    all_files = _all_files()
    optional_keys = {k for k in all_files if k.startswith("product3_")}
    try:
        bulk = download_files(config, all_files, optional=optional_keys, force=False)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc

    if bulk.not_modified and config.db_path.exists():
        meta = _read_meta(config.db_path)
        version = meta.orphanet_version if meta else "unknown"
        print(f"Orphanet database is up to date (releases not modified; version {version}).")
        return

    single_paths, classification_paths = _split_paths(bulk)
    try:
        db_path = build_database(config, single_paths, classification_paths)
    except Exception as exc:
        print(f"ERROR: build failed: {exc}")
        raise typer.Exit(code=1) from exc

    meta = _read_meta(db_path)
    if meta is not None:
        _print_meta(meta, header="Orphanet database refreshed:")
    else:
        print(f"Orphanet database refreshed at {db_path}.")


@app.command()
def fetch() -> None:
    """Download the prebuilt database from the GitHub Release (no local build)."""
    from orphanet_link.exceptions import DataUnavailableError
    from orphanet_link.services.data_resolver import fetch_prebuilt

    config = get_config()
    try:
        db_path = fetch_prebuilt(config)
    except DataUnavailableError as exc:
        print(f"ERROR: could not fetch prebuilt database: {exc}")
        print("Run `orphanet-link-data build` to build it locally instead.")
        raise typer.Exit(code=1) from exc

    meta = _read_meta(db_path)
    if meta is not None:
        _print_meta(meta, header="Fetched prebuilt Orphanet database:")
    else:
        print(f"Fetched prebuilt Orphanet database at {db_path}.")


@app.command()
def status() -> None:
    """Print provenance of the existing database, or a hint to build it."""
    config = get_config()
    meta = _read_meta(config.db_path)
    if meta is None:
        print(f"No Orphanet database at {config.db_path}.")
        print("Run `orphanet-link-data build` to download and build it.")
        raise typer.Exit(code=1)
    _print_meta(meta, header=f"Orphanet database at {config.db_path}:")


def main() -> None:
    """Console-script entry point for ``orphanet-link-data``."""
    app()


if __name__ == "__main__":
    main()
