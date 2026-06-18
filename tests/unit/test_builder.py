"""Tests for the database builder (assembles all parsers into SQLite)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.constants import SCHEMA_VERSION
from orphanet_link.ingest.builder import build_database

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
