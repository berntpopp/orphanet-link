"""Tests for the SQLite schema DDL."""

from __future__ import annotations

import sqlite3

from orphanet_link.ingest.schema import load_schema_sql


def test_schema_executes_and_has_core_tables():
    conn = sqlite3.connect(":memory:")
    conn.executescript(load_schema_sql())
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "disorder",
        "disorder_synonym",
        "disorder_lookup",
        "xref",
        "classification_edge",
        "classification_closure",
        "specialty",
        "linearisation",
        "gene",
        "disorder_gene",
        "phenotype",
        "prevalence",
        "age_of_onset",
        "inheritance",
        "disability",
        "meta",
    }
    assert expected <= tables


def test_schema_fts_usable():
    conn = sqlite3.connect(":memory:")
    conn.executescript(load_schema_sql())
    conn.execute(
        "INSERT INTO disorder_fts(orpha_code, name, synonyms) VALUES('58','Alexander disease','x')"
    )
    rows = list(
        conn.execute("SELECT orpha_code FROM disorder_fts WHERE disorder_fts MATCH 'Alexander'")
    )
    assert rows and rows[0][0] == "58"


def test_meta_single_row_constraint():
    conn = sqlite3.connect(":memory:")
    conn.executescript(load_schema_sql())
    conn.execute("INSERT INTO meta(id, schema_version) VALUES(1, 1)")
    try:
        conn.execute("INSERT INTO meta(id, schema_version) VALUES(2, 1)")
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised
