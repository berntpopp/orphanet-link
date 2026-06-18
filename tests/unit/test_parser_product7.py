"""Tests for the product7 parser (linearisation / preferential parent)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product7

FX = Path(__file__).parent.parent / "fixtures" / "en_product7.xml"


def test_product7_child_has_parent():
    rows = product7.parse(FX)
    by_code = {r["orpha_code"]: r for r in rows}
    assert "166024" in by_code
    assert by_code["166024"]["parent_code"] == "93419"


def test_product7_root_has_no_parent():
    rows = product7.parse(FX)
    by_code = {r["orpha_code"]: r for r in rows}
    assert "93419" in by_code
    assert by_code["93419"]["parent_code"] is None


def test_product7_returns_all_disorders():
    rows = product7.parse(FX)
    codes = {r["orpha_code"] for r in rows}
    assert codes == {"166024", "93419"}
