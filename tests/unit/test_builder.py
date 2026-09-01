"""Tests for the database builder (assembles all parsers into SQLite)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.constants import SCHEMA_VERSION
from orphanet_link.exceptions import BuildError
from orphanet_link.ingest.builder import _compute_closure, build_database

FX = Path(__file__).parent.parent / "fixtures"


def _build(tmp_path) -> Path:
    cfg = OrphanetDataConfig(data_dir=tmp_path)
    paths = {
        "product1": FX / "en_product1.xml",
        "product4": FX / "en_product4.xml",
        "product6": FX / "en_product6.xml",
        "product7": FX / "en_product7.xml",
        "product9_prev": FX / "en_product9_prev.xml",
        "product9_ages": FX / "en_product9_ages.xml",
        "funct": FX / "en_funct_consequences.xml",
    }
    classification_paths = {"156": FX / "en_product3_156.xml"}
    return build_database(cfg, paths, classification_paths)


def _ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def test_build_populates_core_tables(tmp_path):
    db = _build(tmp_path)
    assert db.exists()
    conn = _ro(db)

    d = conn.execute("SELECT * FROM disorder WHERE orpha_code='166024'").fetchone()
    assert d is not None
    assert d["disorder_type"] == "Disease"
    assert d["definition"].startswith("A rare primary bone dysplasia")

    omim = conn.execute("SELECT * FROM xref WHERE orpha_code='166024' AND source='OMIM'").fetchone()
    assert omim["object_id"] == "607131" and omim["mapping_relation"] == "E"

    gene = conn.execute("SELECT * FROM gene WHERE gene_symbol='KIF7'").fetchone()
    assert gene["hgnc_id"] == "30497"
    dg = conn.execute(
        "SELECT * FROM disorder_gene WHERE orpha_code='166024' AND gene_symbol='KIF7'"
    ).fetchone()
    assert dg is not None

    pheno = conn.execute(
        "SELECT * FROM phenotype WHERE orpha_code='58' AND hpo_id='HP:0000256'"
    ).fetchone()
    assert pheno["hpo_term"] == "Macrocephaly"


def test_build_fts_and_lookup(tmp_path):
    db = _build(tmp_path)
    conn = _ro(db)
    hit = conn.execute(
        "SELECT orpha_code FROM disorder_fts WHERE disorder_fts MATCH 'Alexander'"
    ).fetchone()
    assert hit["orpha_code"] == "58"
    lk = conn.execute(
        "SELECT orpha_code FROM disorder_lookup WHERE lookup_label=? AND label_type='name'",
        ("ALEXANDER DISEASE",),
    ).fetchone()
    assert lk["orpha_code"] == "58"


def test_build_classification_closure(tmp_path):
    db = _build(tmp_path)
    conn = _ro(db)
    # fixture tree: 156 -> 93419 -> 166024
    edge = conn.execute(
        "SELECT 1 FROM classification_edge WHERE orpha_code='166024' AND parent_code='93419'"
    ).fetchone()
    assert edge is not None
    # transitive ancestor + self-pair
    anc = {
        r[0]
        for r in conn.execute(
            "SELECT ancestor_code FROM classification_closure WHERE orpha_code='166024'"
        )
    }
    assert {"166024", "93419", "156"} <= anc


def test_build_meta(tmp_path):
    db = _build(tmp_path)
    conn = _ro(db)
    meta = conn.execute("SELECT * FROM meta").fetchone()
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["orphanet_version"].startswith("1.3.42")
    assert meta["orphanet_date"].startswith("2025-12-09")
    assert meta["disorder_count"] >= 2


# ---------------------------------------------------------------------------
# Byte reproducibility.  The release pipeline decides "no-op vs collision" by
# rebuilding the current snapshot and comparing it to the published bundle, so a
# build that is not byte-reproducible reports a collision against its own output.
# ---------------------------------------------------------------------------


_CLOSURE_PROBE = """
import hashlib
import sys

from orphanet_link.ingest.builder import _compute_closure

# ~5k synthetic edges: enough nodes that set iteration order actually varies.
edges = [(f"n{i}", f"n{i // 3}", "156") for i in range(1, 5000)]
pairs = _compute_closure(edges)
sys.stdout.write(f"{len(pairs)} {hashlib.sha256(repr(pairs).encode()).hexdigest()}")
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_closure_row_order_is_independent_of_the_hash_seed() -> None:
    """``_compute_closure`` must not leak ``set`` iteration order into row order.

    Regression: both loops iterated sets, so the ~130k closure rows inserted in a
    PYTHONHASHSEED-dependent order.  The row *content* was always identical -- the
    rowids, and therefore the SQLite bytes and the gzip digest, were not.
    """
    results = set()
    for seed in ("0", "1", "2", "3"):
        completed = subprocess.run(  # noqa: S603 -- runs this interpreter on repo code.
            [sys.executable, "-c", _CLOSURE_PROBE],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            check=True,
            text=True,
        )
        results.add(completed.stdout)
    assert len(results) == 1, f"closure order varies with PYTHONHASHSEED: {sorted(results)}"


def test_closure_pairs_are_emitted_in_sorted_order() -> None:
    """The in-process statement of the same contract, without a subprocess."""
    pairs = _compute_closure([("c", "b", "156"), ("b", "a", "156"), ("z", "a", "156")])
    assert pairs == sorted(pairs)


def test_build_is_byte_reproducible(tmp_path):
    """Two builds of one upstream snapshot must produce identical database bytes."""
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second")
    assert _sha256(first) == _sha256(second)


def test_meta_records_no_run_provenance(tmp_path):
    """``build_utc`` follows the source revision; the run duration is not stored."""
    conn = _ro(_build(tmp_path))
    meta = conn.execute("SELECT * FROM meta").fetchone()
    # <JDBOR date="2025-12-09 07:06:32"> in tests/fixtures/en_product1.xml.
    assert meta["build_utc"] == "2025-12-09T07:06:32+00:00"
    assert meta["build_duration_s"] is None


def test_source_date_epoch_pins_the_build_stamp(tmp_path, monkeypatch):
    """A caller may pin ``build_utc`` explicitly; it still never reads the clock."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    conn = _ro(_build(tmp_path))
    assert conn.execute("SELECT build_utc FROM meta").fetchone()[0] == "2023-11-14T22:13:20+00:00"


def test_invalid_source_date_epoch_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "not-a-timestamp")
    with pytest.raises(BuildError, match="SOURCE_DATE_EPOCH"):
        _build(tmp_path)
