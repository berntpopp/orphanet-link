"""Tests for the product9_ages parser (natural history: age of onset + inheritance)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product9_ages

FX = Path(__file__).parent.parent / "fixtures" / "en_product9_ages.xml"


def test_onsets_disorder_166024():
    result = product9_ages.parse(FX)
    assert ("166024", "Infancy") in result.onsets
    assert ("166024", "Neonatal") in result.onsets


def test_inheritance_disorder_166024():
    result = product9_ages.parse(FX)
    assert ("166024", "Autosomal recessive") in result.inheritance


def test_onsets_disorder_166032():
    result = product9_ages.parse(FX)
    assert ("166032", "Childhood") in result.onsets


def test_no_inheritance_for_166032():
    result = product9_ages.parse(FX)
    codes = {code for code, _ in result.inheritance}
    assert "166032" not in codes
