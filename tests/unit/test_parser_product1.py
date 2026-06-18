"""Tests for the product1 parser + shared _common helpers."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import _common, product1

FX = Path(__file__).parent.parent / "fixtures" / "en_product1.xml"


def test_product1_parses_disorder():
    res = product1.parse(FX)
    by_code = {d["orpha_code"]: d for d in res.disorders}
    assert set(by_code) == {"166024", "58"}
    d = by_code["166024"]
    assert d["name"].startswith("Multiple epiphyseal dysplasia")
    assert d["disorder_type"] == "Disease"
    assert d["disorder_group"] == "Disorder"
    assert d["disorder_flag"] == "1"
    assert d["definition"].startswith("A rare primary bone dysplasia")
    assert d["expert_link"].startswith("http://www.orpha.net")
    alex = by_code["58"]
    assert alex["synonyms"] == ["AxD", "Fibrinoid leukodystrophy"]


def test_product1_parses_xrefs():
    res = product1.parse(FX)
    xr = [x for x in res.xrefs if x["orpha_code"] == "166024"]
    sources = {x["source"] for x in xr}
    assert {"ICD-11", "MONDO", "ICD-10", "OMIM", "UMLS"} == sources

    omim = next(x for x in xr if x["source"] == "OMIM")
    assert omim["object_id"] == "607131"
    assert omim["mapping_relation"] == "E"
    assert omim["validation_status"] == "Validated"

    icd11 = next(x for x in xr if x["source"] == "ICD-11")
    assert icd11["object_id"] == "LD24.61"
    assert icd11["mapping_relation"] == "NTBT"
    assert icd11["icd_relation"] == "Index"  # leading token of the ICD relation name
    assert icd11["ref_uri"].startswith("https://icd.who.int")


def test_jdbor_stamp():
    date, version = _common.jdbor_stamp(FX)
    assert date.startswith("2025-12-09")
    assert version.startswith("1.3.42")
