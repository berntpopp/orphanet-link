"""Tests for the product3 parser — rare-disease classification trees."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product3

FX = Path(__file__).parent.parent / "fixtures" / "en_product3_156.xml"


def test_product3_specialty():
    res = product3.parse(FX, "156")
    assert res.specialty is not None
    assert res.specialty["specialty_id"] == "156"
    assert "genetic" in res.specialty["name"].lower()


def test_product3_edges_parent_child():
    res = product3.parse(FX, "156")
    by_child = {e["orpha_code"]: e for e in res.edges}

    # child 93419 has parent 156
    assert "93419" in by_child
    assert by_child["93419"]["parent_code"] == "156"
    assert by_child["93419"]["specialty_id"] == "156"

    # child 166024 has parent 93419
    assert "166024" in by_child
    assert by_child["166024"]["parent_code"] == "93419"
    assert by_child["166024"]["specialty_id"] == "156"


def test_product3_root_has_no_edge():
    res = product3.parse(FX, "156")
    child_codes = {e["orpha_code"] for e in res.edges}
    # root node (OrphaCode 156) must not appear as a child
    assert "156" not in child_codes


def test_product3_edge_count():
    res = product3.parse(FX, "156")
    # fixture has exactly 2 edges: 156->93419 and 93419->166024
    assert len(res.edges) == 2
