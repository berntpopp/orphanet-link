"""Boundary / limit / pagination contract tests (characterization).

These pin the EXISTING boundary behaviour of the data plane (``OrphanetService``)
and the batch tool layer (the wired ``facade``): limit clamping, offset-past-total
returning an empty non-truncated page, the batch hard cap, the ``include_obsolete``
superset guarantee, and a golden forward-pagination walk that reassembles a full
result set page-by-page with no duplicate or missing rows. No source changes are
made; every assertion mirrors the canonical pagination block defined in
``orphanet_link.services.pagination.page_fields``
(``total``/``returned``/``limit``/``offset``/``truncated``/``next_offset``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from orphanet_link.services.orphanet_service import OrphanetService
from tests.unit._envelope import envelope

# Fixture facts (see tests/conftest.py + tests/fixtures/):
_ORPHA_KIF7 = "ORPHA:166024"  # classification child of 93419, child of root 156
_ORPHA_58 = "ORPHA:58"  # "Alexander disease"
_ROOT = "ORPHA:156"  # classification root: 156 -> 93419 -> 166024
_OMIM_KIF7 = "OMIM:607131"  # xref of ORPHA:166024
# A broad FTS term that returns both fixture disorders (58 and 166024).
_BROAD_QUERY = "a"


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    tools = await _tools(facade)
    result: dict[str, Any] = envelope(await tools[name].fn(**kwargs))
    return result


# ---------------------------------------------------------------------------
# 1. Limit clamping (service level): search clamps to [1, 200];
#    closure / xref clamp to [1, 1000] (_MAX_LIMIT).
# ---------------------------------------------------------------------------


def test_search_limit_capped_to_200(service: OrphanetService) -> None:
    assert service.search_diseases(_BROAD_QUERY, limit=10_000)["limit"] == 200


def test_search_limit_zero_floored_to_one(service: OrphanetService) -> None:
    assert service.search_diseases(_BROAD_QUERY, limit=0)["limit"] == 1


def test_search_limit_negative_floored_to_one(service: OrphanetService) -> None:
    assert service.search_diseases(_BROAD_QUERY, limit=-5)["limit"] == 1


def test_ancestors_limit_capped_to_1000(service: OrphanetService) -> None:
    assert service.get_disease_ancestors(_ORPHA_KIF7, limit=10_000)["limit"] == 1000


def test_descendants_limit_capped_to_1000(service: OrphanetService) -> None:
    assert service.get_disease_descendants(_ROOT, limit=10_000)["limit"] == 1000


def test_resolve_xref_limit_capped_to_1000(service: OrphanetService) -> None:
    assert service.resolve_xref(_OMIM_KIF7, limit=10_000)["limit"] == 1000


# ---------------------------------------------------------------------------
# 2. Offset past total -> empty page, truncated False (no next_offset emitted).
# ---------------------------------------------------------------------------


def test_search_offset_past_total_is_empty_not_truncated(service: OrphanetService) -> None:
    result = service.search_diseases("Alexander", offset=9999)
    assert result["results"] == []
    assert result["returned"] == 0
    assert result["truncated"] is False
    assert "next_offset" not in result


def test_ancestors_offset_past_total_is_empty_not_truncated(service: OrphanetService) -> None:
    # Closure tools route the payload through compact shaping (the default), which
    # drops empty-list keys -- so an empty page omits the `ancestors` key entirely
    # rather than carrying `[]`. The pagination block still reports an empty,
    # non-truncated page. (In `standard` mode the key survives as `[]`; asserted
    # below to prove the absence is a shaping artifact, not a data error.)
    result = service.get_disease_ancestors(_ORPHA_KIF7, offset=9999)
    assert "ancestors" not in result
    assert result["returned"] == 0
    assert result["truncated"] is False
    assert "next_offset" not in result
    standard = service.get_disease_ancestors(_ORPHA_KIF7, offset=9999, response_mode="standard")
    assert standard["ancestors"] == []
    assert standard["returned"] == 0
    assert standard["truncated"] is False


def test_descendants_offset_past_total_is_empty_not_truncated(service: OrphanetService) -> None:
    # Same compact-shaping contract as the ancestors case above.
    result = service.get_disease_descendants(_ROOT, offset=9999)
    assert "descendants" not in result
    assert result["returned"] == 0
    assert result["truncated"] is False
    assert "next_offset" not in result
    standard = service.get_disease_descendants(_ROOT, offset=9999, response_mode="standard")
    assert standard["descendants"] == []
    assert standard["returned"] == 0
    assert standard["truncated"] is False


# ---------------------------------------------------------------------------
# 3. Batch > MAX_BATCH_ITEMS (50) and empty batch -> invalid_input (TOOL layer).
# ---------------------------------------------------------------------------


async def test_get_disease_batch_over_cap_is_invalid_input(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_batch", terms=[_ORPHA_58] * 51)
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "terms"


async def test_resolve_disease_batch_over_cap_is_invalid_input(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=[_ORPHA_58] * 51)
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "queries"


async def test_get_disease_batch_empty_is_invalid_input(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_batch", terms=[])
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "terms"


async def test_resolve_disease_batch_empty_is_invalid_input(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=[])
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "queries"


# ---------------------------------------------------------------------------
# 4. include_obsolete is a superset: turning it on never narrows the result set.
#    (The fixture has 0 obsolete disorders, so it is equal here; the test
#    documents that the param is plumbed and only ever widens.)
# ---------------------------------------------------------------------------


def test_include_obsolete_is_a_superset(service: OrphanetService) -> None:
    with_obsolete = service.search_diseases(_BROAD_QUERY, include_obsolete=True)
    without_obsolete = service.search_diseases(_BROAD_QUERY, include_obsolete=False)
    assert without_obsolete["total"] >= 1  # the query must actually hit something
    assert with_obsolete["total"] >= without_obsolete["total"]


# ---------------------------------------------------------------------------
# 5. Golden forward-pagination walk: stepping offset by page=1 reassembles the
#    full set exactly (no duplicate, none missing) and matches a single
#    large-limit call.
# ---------------------------------------------------------------------------


def _walk_all_codes(
    page_fn: Callable[[int], dict[str, Any]],
    rows_key: str,
    *,
    page: int = 1,
) -> list[str]:
    """Walk ``offset`` in steps of ``page`` collecting every row's orpha_code.

    Uses ``total`` from the first page as the loop bound and follows the
    pagination contract: ``truncated`` flags more rows ahead and ``next_offset``
    (when present) is the offset to fetch next.
    """
    collected: list[str] = []
    offset = 0
    total: int | None = None
    while True:
        result = page_fn(offset)
        if total is None:
            total = result["total"]
        rows = result[rows_key]
        collected.extend(str(row["orpha_code"]) for row in rows)
        if not result["truncated"]:
            break
        offset = result["next_offset"]
    assert total is not None
    assert len(collected) == total, f"walked {len(collected)} rows but total={total}"
    return collected


def _assert_reassembles(walked: list[str], full: list[str]) -> None:
    """Collected codes must be the full set with no duplicate and none missing."""
    assert len(walked) == len(set(walked)), f"duplicate rows in walk: {walked}"
    assert set(walked) == set(full)


def test_pagination_walk_search_reassembles_total(service: OrphanetService) -> None:
    full = [
        str(r["orpha_code"]) for r in service.search_diseases(_BROAD_QUERY, limit=200)["results"]
    ]
    assert len(full) >= 2, "need >=2 hits to exercise multi-page reassembly"
    walked = _walk_all_codes(
        lambda off: service.search_diseases(_BROAD_QUERY, limit=1, offset=off),
        "results",
    )
    _assert_reassembles(walked, full)


def test_pagination_walk_ancestors_reassembles_total(service: OrphanetService) -> None:
    full = [
        str(r["orpha_code"])
        for r in service.get_disease_ancestors(_ORPHA_KIF7, limit=1000)["ancestors"]
    ]
    assert len(full) == 2  # {156, 93419}
    walked = _walk_all_codes(
        lambda off: service.get_disease_ancestors(_ORPHA_KIF7, limit=1, offset=off),
        "ancestors",
    )
    _assert_reassembles(walked, full)


def test_pagination_walk_descendants_reassembles_total(service: OrphanetService) -> None:
    full = [
        str(r["orpha_code"])
        for r in service.get_disease_descendants(_ROOT, limit=1000)["descendants"]
    ]
    assert len(full) == 2  # {93419, 166024}
    walked = _walk_all_codes(
        lambda off: service.get_disease_descendants(_ROOT, limit=1, offset=off),
        "descendants",
    )
    _assert_reassembles(walked, full)
