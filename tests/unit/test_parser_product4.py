"""Tests for the product4 parser (HPO phenotype associations)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product4

FX = Path(__file__).parent.parent / "fixtures" / "en_product4.xml"


def test_product4_returns_rows_for_orpha_code_58():
    rows = product4.parse(FX)
    orpha_58 = [r for r in rows if r["orpha_code"] == "58"]
    assert len(orpha_58) >= 2


def test_product4_macrocephaly_row():
    rows = product4.parse(FX)
    row = next(r for r in rows if r["hpo_id"] == "HP:0000256")
    assert row["orpha_code"] == "58"
    assert row["hpo_term"] == "Macrocephaly"
    assert row["frequency"] == "Very frequent (99-80%)"


def test_product4_row_keys():
    rows = product4.parse(FX)
    assert rows, "parse must return at least one row"
    expected_keys = {"orpha_code", "hpo_id", "hpo_term", "frequency", "diagnostic_criteria"}
    assert set(rows[0].keys()) == expected_keys
