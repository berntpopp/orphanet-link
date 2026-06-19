"""Tests for orphanet_link.identifiers."""

from __future__ import annotations

from orphanet_link.identifiers import (
    is_orpha_code,
    normalize_hpo_id,
    normalize_orpha_code,
    parse_curie,
)


def test_normalize_orpha_code():
    assert normalize_orpha_code("ORPHA:166024") == "166024"
    assert normalize_orpha_code("Orphanet:166024") == "166024"
    assert normalize_orpha_code("orpha_166024") == "166024"
    assert normalize_orpha_code("166024") == "166024"
    assert normalize_orpha_code("not a code") is None
    assert normalize_orpha_code("") is None


def test_is_orpha_code():
    assert is_orpha_code("166024") is True
    assert is_orpha_code("OMIM:607131") is False


def test_normalize_hpo_id_canonical_forms():
    assert normalize_hpo_id("HP:0000256") == "HP:0000256"
    assert normalize_hpo_id("hp:0000256") == "HP:0000256"
    assert normalize_hpo_id("HPO:0000256") == "HP:0000256"
    assert normalize_hpo_id("HP_0000256") == "HP:0000256"
    assert normalize_hpo_id("HP0000256") == "HP:0000256"
    assert normalize_hpo_id("  HP:0000256  ") == "HP:0000256"


def test_normalize_hpo_id_rejects_malformed():
    assert normalize_hpo_id("HP:000256") is None  # 6 digits (dropped digit)
    assert normalize_hpo_id("HP:00002566") is None  # 8 digits
    assert normalize_hpo_id("NOT_AN_HPO_ID") is None
    assert normalize_hpo_id("0000256") is None  # bare number, no HP prefix
    assert normalize_hpo_id("OMIM:607131") is None
    assert normalize_hpo_id("") is None


def test_parse_curie():
    assert parse_curie("OMIM:607131") == ("OMIM", "607131")
    assert parse_curie("icd-10:Q77.3") == ("ICD-10", "Q77.3")
    assert parse_curie("mesh:D000130") == ("MeSH", "D000130")
    assert parse_curie("HP:0000256") == ("HP", "0000256")
    # unknown prefix / free text -> no prefix
    assert parse_curie("Alexander disease") == (None, "Alexander disease")
    assert parse_curie("foo:bar") == (None, "foo:bar")
