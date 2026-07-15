"""P2 batch-robustness contracts (assessment F-01).

A batch item that fails with ambiguous_query must be as self-recoverable as the
single-call equivalent: it carries candidates[] so the agent can pick one without
a second round trip. Each item also carries a stable index for correlation, and a
batch over the hard cap is rejected (logged), never silently truncated.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastmcp import FastMCP

from tests.unit._envelope import envelope

_ORPHA_58 = "ORPHA:58"
_AMBIGUOUS = "a"  # FTS-matches both fixture disorders -> ambiguous_query


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return envelope(await (await _tools(facade))[name].fn(**kwargs))


# --- P2.1: ambiguous batch items carry candidates -----------------------------


async def test_resolve_batch_ambiguous_item_carries_candidates(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=[_ORPHA_58, _AMBIGUOUS])
    assert result["success"] is True  # call never fails wholesale
    bad = result["results"][1]
    assert bad["ok"] is False
    assert bad["error_code"] == "ambiguous_query"
    candidates = bad.get("candidates")
    assert candidates, "ambiguous batch item must carry recoverable candidates[]"
    assert all("orpha_code" in c for c in candidates)


async def test_get_disease_batch_ambiguous_item_carries_candidates(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_batch", terms=[_AMBIGUOUS, _ORPHA_58])
    bad = result["results"][0]
    assert bad["ok"] is False
    assert bad["error_code"] == "ambiguous_query"
    assert bad.get("candidates"), "ambiguous batch item must carry candidates[]"


async def test_candidate_count_respects_response_mode(facade: FastMCP) -> None:
    minimal = await _call(
        facade, "resolve_disease_batch", queries=[_AMBIGUOUS], response_mode="minimal"
    )
    full = await _call(facade, "resolve_disease_batch", queries=[_AMBIGUOUS], response_mode="full")
    min_cands = minimal["results"][0].get("candidates", [])
    full_cands = full["results"][0].get("candidates", [])
    assert len(min_cands) <= 1, "minimal must trim candidate count"
    assert len(full_cands) >= len(min_cands)
    assert len(full_cands) == 2, "full must carry every candidate (2 in fixtures)"


# --- P2.2: stable per-item index ----------------------------------------------


async def test_batch_items_carry_stable_index(facade: FastMCP) -> None:
    result = await _call(
        facade, "resolve_disease_batch", queries=[_ORPHA_58, _AMBIGUOUS, "ORPHA:9999999"]
    )
    assert [row["index"] for row in result["results"]] == [0, 1, 2]


async def test_get_disease_batch_items_carry_index(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_batch", terms=[_ORPHA_58, _ORPHA_58])
    assert [row["index"] for row in result["results"]] == [0, 1]


# --- P2.3: over-cap rejected and logged ---------------------------------------


async def test_over_cap_batch_rejected_and_logged(
    facade: FastMCP, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = await _call(facade, "resolve_disease_batch", queries=[_ORPHA_58] * 51)
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "queries"
    assert any("cap" in r.getMessage().lower() for r in caplog.records), (
        "the cap rejection must emit a dedicated log line"
    )
