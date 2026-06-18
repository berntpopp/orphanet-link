"""Tests for the funct_consequences parser (disability annotations)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import funct_consequences

FX = Path(__file__).parent.parent / "fixtures" / "en_funct_consequences.xml"


def test_funct_consequences_returns_rows_for_orpha_code_893():
    rows = funct_consequences.parse(FX)
    orpha_893 = [r for r in rows if r["orpha_code"] == "893"]
    assert len(orpha_893) >= 1


def test_funct_consequences_annotation_row():
    rows = funct_consequences.parse(FX)
    row = next(r for r in rows if r["orpha_code"] == "893")
    assert row["annotation"].startswith("Managing one's health")
    assert row["frequency"] == "Very frequent"
    assert row["temporality"] == "Permanent limitation"
    assert row["severity"] == "Severe"


def test_funct_consequences_row_keys():
    rows = funct_consequences.parse(FX)
    assert rows, "parse must return at least one row"
    expected_keys = {"orpha_code", "annotation", "frequency", "temporality", "severity"}
    assert set(rows[0].keys()) == expected_keys
