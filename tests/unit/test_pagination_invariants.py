"""Property tests for the uniform pagination block on every list tool (P3.3).

Every list-returning tool stamps the canonical truncation + forward-pagination
block from ``orphanet_link/services/pagination.py::page_fields``: ``total``,
``returned``, ``limit``, ``offset``, ``truncated``, and (only when truncated)
``next_offset``. These tests pin those invariants across all list tools and a
range of page windows -- including a window that actually hits truncation and a
window past the end -- so the contract an LLM relies on to page forward without
re-fetching the head can never silently drift.

``response_mode="standard"`` is used deliberately: standard keeps the rows key
even when the page is empty (compact drops empty lists), so ``len(rows)`` stays
well-defined for the ``returned == len(rows)`` invariant.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

_ORPHA_KIF7 = "ORPHA:166024"  # ancestors closure = {156, 93419} (total 2)
_ORPHA_156 = "ORPHA:156"  # descendants closure = {93419, 166024} (total 2)

#: (tool_name, base_kwargs, rows_key) for every list-returning tool. The base_kwargs are
#: genuinely per-tool (each needs a fixture id/label that returns rows), so they cannot be
#: derived -- but the COMPLETENESS of this list is not left to memory:
#: ``test_every_paginated_tool_is_covered`` derives the set of paginated tools from the
#: registry and fails if any is missing here. A hardcoded list nobody guards is the bug one
#: level up; a hardcoded list a derived guard pins is just a fixture table.
_LIST_TOOLS: list[tuple[str, dict[str, Any], str]] = [
    ("search_diseases", {"query": "a"}, "results"),
    ("get_disease_ancestors", {"term": _ORPHA_KIF7}, "ancestors"),
    ("get_disease_descendants", {"term": _ORPHA_156}, "descendants"),
    ("resolve_xref", {"xref_id": "OMIM:607131"}, "matches"),
    ("find_diseases_by_gene", {"gene_symbol": "KIF7"}, "results"),
    ("find_diseases_by_phenotype", {"hpo_id": "HP:0000256"}, "results"),
]

#: The signature of a paginated tool: it offers BOTH a forward-page offset and a page cap.
_PAGINATION_PARAMS = frozenset({"limit", "offset"})

#: Page windows exercised per tool: small page, next page, oversized page (no
#: truncation), and an offset past the end (empty page, no next_offset).
_WINDOWS: list[tuple[int, int]] = [
    (1, 0),
    (1, 1),
    (1000, 0),
    (5, 9999),
]


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def test_every_paginated_tool_is_covered(facade: FastMCP) -> None:
    """Derive the paginated tools from the registry; none may be missing from _LIST_TOOLS.

    So a newly-added list tool cannot ship with its pagination invariants ungated: it
    breaks the build until it is given a fixture row here.
    """
    covered = {name for name, _, _ in _LIST_TOOLS}
    paginated = {
        tool.name
        for tool in await facade.list_tools()
        if set((getattr(tool, "parameters", None) or {}).get("properties", {}))
        >= _PAGINATION_PARAMS
    }
    missing = paginated - covered
    assert not missing, (
        f"these tools accept limit+offset but are not in _LIST_TOOLS, so their pagination "
        f"invariants are untested: {sorted(missing)}"
    )
    stale = covered - paginated
    assert not stale, f"_LIST_TOOLS names tools that are not paginated: {sorted(stale)}"


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return await (await _tools(facade))[name].fn(**kwargs)


def _assert_pagination_invariants(result: dict[str, Any], rows_key: str) -> None:
    """Assert the canonical ``page_fields`` invariants on a list-tool payload."""
    assert result["success"] is True
    # standard mode keeps the rows key even on an empty page.
    assert rows_key in result, f"{rows_key} must be present in standard mode"
    rows = result[rows_key]
    assert isinstance(rows, list)

    total = result["total"]
    returned = result["returned"]
    limit = result["limit"]
    offset = result["offset"]
    truncated = result["truncated"]

    # 1. returned counts exactly the rows shipped on this page.
    assert returned == len(rows), f"returned={returned} != len(rows)={len(rows)}"
    # 2. truncated iff more rows remain beyond this page.
    assert truncated == (offset + returned < total)
    # 3. next_offset is present iff truncated, and equals offset + returned.
    if truncated:
        assert result["next_offset"] == offset + returned
    else:
        assert "next_offset" not in result, "next_offset must be absent when not truncated"
    # 4. a page never ships more rows than the cap allows.
    assert returned <= limit


@pytest.mark.parametrize(("name", "base_kwargs", "rows_key"), _LIST_TOOLS)
@pytest.mark.parametrize(("limit", "offset"), _WINDOWS)
async def test_pagination_invariants_hold(
    facade: FastMCP,
    name: str,
    base_kwargs: dict[str, Any],
    rows_key: str,
    limit: int,
    offset: int,
) -> None:
    """``page_fields`` invariants hold for every list tool across every window."""
    result = await _call(
        facade, name, response_mode="standard", limit=limit, offset=offset, **base_kwargs
    )
    _assert_pagination_invariants(result, rows_key)


@pytest.mark.parametrize(("name", "base_kwargs", "rows_key"), _LIST_TOOLS)
async def test_offset_past_end_yields_empty_untruncated_page(
    facade: FastMCP,
    name: str,
    base_kwargs: dict[str, Any],
    rows_key: str,
) -> None:
    """An offset past the end returns zero rows, ``truncated=False``, no ``next_offset``."""
    result = await _call(
        facade, name, response_mode="standard", limit=5, offset=9999, **base_kwargs
    )
    assert result["success"] is True
    assert result[rows_key] == []
    assert result["returned"] == 0
    assert result["truncated"] is False
    assert "next_offset" not in result


async def test_truncated_branch_is_actually_exercised(facade: FastMCP) -> None:
    """A first small page over a >1-row result truly hits the truncated branch.

    ``search_diseases("a")`` matches both fixture disorders (total 2), so a
    ``limit=1`` first page must report ``truncated`` with ``next_offset=1`` and
    the second page must close it out (``truncated=False``, no ``next_offset``).
    """
    first = await _call(facade, "search_diseases", query="a", response_mode="standard", limit=1)
    assert first["total"] == 2
    assert first["returned"] == 1
    assert first["truncated"] is True
    assert first["next_offset"] == 1

    second = await _call(
        facade, "search_diseases", query="a", response_mode="standard", limit=1, offset=1
    )
    assert second["returned"] == 1
    assert second["truncated"] is False
    assert "next_offset" not in second
