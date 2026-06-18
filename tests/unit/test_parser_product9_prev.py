"""Tests for the product9_prev parser (epidemiology / prevalence)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product9_prev

FX = Path(__file__).parent.parent / "fixtures" / "en_product9_prev.xml"


def test_product9_prev_two_rows_for_disorder():
    rows = product9_prev.parse(FX)
    rows_166024 = [r for r in rows if r["orpha_code"] == "166024"]
    assert len(rows_166024) == 2


def test_product9_prev_point_prevalence_row():
    rows = product9_prev.parse(FX)
    row = next(r for r in rows if r["prevalence_type"] == "Point prevalence")
    assert row["orpha_code"] == "166024"
    assert row["prevalence_class"] == "<1 / 1 000 000"
    assert row["geographic"] == "Worldwide"
    assert row["validation_status"] == "Validated"
    assert row["qualification"] == "Class only"


def test_product9_prev_cases_families_row():
    rows = product9_prev.parse(FX)
    row = next(r for r in rows if r["prevalence_type"] == "Cases/families")
    assert row["val_moy"] == 4.0
    assert row["prevalence_class"] is None
    assert row["orpha_code"] == "166024"
