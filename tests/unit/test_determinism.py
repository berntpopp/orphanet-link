"""Ordering / determinism contract tests (assessment phase P4).

These lock the ordering and determinism guarantees of the data plane
(``OrphanetService``) and prove the MCP envelope (the wired ``facade``) does not
perturb that order. Three properties are pinned:

* **Run-to-run byte-identical ordering** (P4.2/P4.3): repeating a call yields the
  exact same row sequence, so FTS ties and closure walks break deterministically
  across runs -- not merely the same *set*, the same *order*.
* **Cross-page no-overlap / no-skip** (P4.2): walking a list one row per page
  (``limit=1``) never repeats a row on two pages, never drops one, and the union
  of pages equals both the single-call full set and the reported ``total``.
* **Determinism through the MCP envelope** (P4.3): the same query issued twice via
  the facade returns identically-ordered ``results``.

Observed tie order (query ``"a"``, both hits scoring 0.0): ORPHAcode ascending --
``ORPHA:58`` precedes ``ORPHA:166024``. This is asserted explicitly because it is
stable across runs. No source files are modified; complementary to the golden
forward-pagination walk in ``tests/unit/test_boundaries.py`` (which checks
reassembly): here we additionally assert NO row appears on two pages.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from orphanet_link.services.orphanet_service import OrphanetService

# Fixture facts (see tests/conftest.py + tests/fixtures/):
_ORPHA_KIF7 = "ORPHA:166024"  # classification child of 93419, child of root 156
_ROOT = "ORPHA:156"  # classification root: 156 -> 93419 -> 166024
# A broad FTS term that returns both fixture disorders (58 and 166024), both 0.0.
_BROAD_QUERY = "a"


def _codes(rows: list[dict[str, Any]]) -> list[str]:
    """Project a list of row dicts onto their ``orpha_code`` values, in order."""
    return [str(row["orpha_code"]) for row in rows]


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


# ---------------------------------------------------------------------------
# 1. Run-to-run byte-identical ordering (P4.2/P4.3): the SAME call twice must
#    produce the SAME row sequence -- ties and closures are stably ordered.
# ---------------------------------------------------------------------------


def test_search_ordering_is_run_to_run_identical(service: OrphanetService) -> None:
    first = service.search_diseases(_BROAD_QUERY, limit=200)["results"]
    second = service.search_diseases(_BROAD_QUERY, limit=200)["results"]
    assert len(first) >= 2, "need >=2 hits to exercise a tiebreak"
    # Identical order, not just same set -- the whole row list compares equal.
    assert first == second


def test_search_tie_order_is_orphacode_ascending(service: OrphanetService) -> None:
    """Both hits score 0.0; the documented tiebreak is ORPHAcode ascending.

    Asserted explicitly because the order is stable run-to-run (proved above):
    ``ORPHA:58`` precedes ``ORPHA:166024`` (58 < 166024).
    """
    rows = service.search_diseases(_BROAD_QUERY, limit=200)["results"]
    scores = {float(r.get("score", 0.0)) for r in rows}
    assert scores == {0.0}, f"expected a pure score tie, got scores={scores}"
    codes = _codes(rows)
    assert codes == ["58", "166024"]
    assert codes == sorted(codes, key=int), "tie must break on ORPHAcode ascending"


def test_ancestors_ordering_is_run_to_run_identical(service: OrphanetService) -> None:
    first = service.get_disease_ancestors(_ORPHA_KIF7, limit=1000)["ancestors"]
    second = service.get_disease_ancestors(_ORPHA_KIF7, limit=1000)["ancestors"]
    assert _codes(first) and set(_codes(first)) == {"156", "93419"}
    assert first == second


def test_descendants_ordering_is_run_to_run_identical(service: OrphanetService) -> None:
    first = service.get_disease_descendants(_ROOT, limit=1000)["descendants"]
    second = service.get_disease_descendants(_ROOT, limit=1000)["descendants"]
    assert _codes(first) and set(_codes(first)) == {"93419", "166024"}
    assert first == second


# ---------------------------------------------------------------------------
# 2. Cross-page no-overlap / no-skip (P4.2): walking the list one row per page
#    must never repeat a row, never drop one, and reassemble exactly the total.
# ---------------------------------------------------------------------------


def _walk_pages(
    page_fn: Callable[[int], dict[str, Any]],
    rows_key: str,
) -> list[list[str]]:
    """Walk ``offset`` one row at a time, returning each page's orpha_codes.

    Follows the pagination contract: ``limit=1`` per page, advancing ``offset``
    via the returned ``next_offset`` while ``truncated`` flags more rows ahead.
    Uses ``response_mode="standard"`` via ``page_fn`` so the rows key always
    survives (compact shaping drops an empty list); we still ``.get`` defensively.
    """
    pages: list[list[str]] = []
    offset = 0
    while True:
        result = page_fn(offset)
        pages.append(_codes(result.get(rows_key, [])))
        if not result.get("truncated"):
            break
        offset = result["next_offset"]
    return pages


def _assert_no_overlap_no_skip(
    pages: list[list[str]],
    full: list[str],
    total: int,
) -> None:
    """No code on two pages; union equals the full single-call set and total."""
    flat = [code for page in pages for code in page]
    # (a) no overlap: every walked code is distinct -> no code on two pages.
    assert len(flat) == len(set(flat)), f"a row appeared on two pages: {pages}"
    # explicit pairwise no-overlap across distinct pages (mirrors P4.2 wording).
    seen: set[str] = set()
    for page in pages:
        page_set = set(page)
        assert not (page_set & seen), f"overlap between pages: {pages}"
        seen |= page_set
    # (b) no skip: the walked set equals the single-call full set.
    assert set(flat) == set(full)
    # (c) the walk reassembles exactly ``total`` rows.
    assert len(flat) == total, f"walked {len(flat)} rows but total={total}"


def test_search_pagination_no_overlap_no_skip(service: OrphanetService) -> None:
    snapshot = service.search_diseases(_BROAD_QUERY, limit=200)
    full = _codes(snapshot["results"])
    total = snapshot["total"]
    assert len(full) >= 2, "need >=2 hits to exercise multi-page walking"
    pages = _walk_pages(
        lambda off: service.search_diseases(_BROAD_QUERY, limit=1, offset=off),
        "results",
    )
    _assert_no_overlap_no_skip(pages, full, total)


def test_ancestors_pagination_no_overlap_no_skip(service: OrphanetService) -> None:
    snapshot = service.get_disease_ancestors(_ORPHA_KIF7, limit=1000, response_mode="standard")
    full = _codes(snapshot["ancestors"])
    total = snapshot["total"]
    assert len(full) == 2  # {156, 93419}
    pages = _walk_pages(
        lambda off: service.get_disease_ancestors(
            _ORPHA_KIF7, limit=1, offset=off, response_mode="standard"
        ),
        "ancestors",
    )
    _assert_no_overlap_no_skip(pages, full, total)


def test_descendants_pagination_no_overlap_no_skip(service: OrphanetService) -> None:
    snapshot = service.get_disease_descendants(_ROOT, limit=1000, response_mode="standard")
    full = _codes(snapshot["descendants"])
    total = snapshot["total"]
    assert len(full) == 2  # {93419, 166024}
    pages = _walk_pages(
        lambda off: service.get_disease_descendants(
            _ROOT, limit=1, offset=off, response_mode="standard"
        ),
        "descendants",
    )
    _assert_no_overlap_no_skip(pages, full, total)


# ---------------------------------------------------------------------------
# 3. Determinism through the MCP envelope (P4.3): the same query twice via the
#    facade must return identically-ordered ``results`` -- the envelope (success
#    flag + _meta) must not perturb the underlying data-plane order.
# ---------------------------------------------------------------------------


async def test_search_ordering_is_identical_through_facade(facade: FastMCP) -> None:
    tools = await _tools(facade)
    first = await tools["search_diseases"].fn(query=_BROAD_QUERY, response_mode="standard")
    second = await tools["search_diseases"].fn(query=_BROAD_QUERY, response_mode="standard")
    assert first["success"] is True and second["success"] is True
    assert len(first["results"]) >= 2, "need >=2 hits to exercise a tiebreak"
    # Identical ordering across the two envelope calls.
    assert _codes(first["results"]) == _codes(second["results"])
    # And the envelope preserves the data-plane tie order (58 before 166024).
    assert _codes(first["results"]) == ["58", "166024"]
