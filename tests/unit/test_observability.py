"""P5 observability contracts.

get_diagnostics' runtime block now surfaces two signals it previously lacked:
- a response_mode distribution (surfaces whether agents over-fetch), and
- a version-hash cache hit/miss ratio.
request_id is emitted on the structured error log line as well as the payload so a
single id traces a call from stderr to response.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastmcp import FastMCP

from orphanet_link.mcp import metrics
from tests.unit._envelope import envelope

_ORPHA_KIF7 = "ORPHA:166024"


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return envelope(await (await _tools(facade))[name].fn(**kwargs))


# --- P5.2: response_mode distribution -----------------------------------------


async def test_runtime_reports_response_mode_distribution(facade: FastMCP) -> None:
    metrics.reset()
    await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="compact")
    await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="minimal")
    await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="standard")
    diag = await _call(facade, "get_diagnostics")
    modes = diag["runtime"]["response_modes"]
    # The get_diagnostics call itself is recorded AFTER its own snapshot, so the
    # histogram reflects exactly the three get_disease calls above.
    assert modes.get("compact") == 1
    assert modes.get("minimal") == 1
    assert modes.get("standard") == 1


async def test_per_tool_runtime_tracks_modes(facade: FastMCP) -> None:
    metrics.reset()
    await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="full")
    diag = await _call(facade, "get_diagnostics")
    per_tool = diag["runtime"]["per_tool"]["get_disease"]
    assert per_tool["modes"].get("full") == 1


# --- P5.1: cache hit/miss -----------------------------------------------------


def test_cache_block_counts_hits_and_misses() -> None:
    metrics.reset()
    metrics.record_cache("capabilities_version", hit=False)
    metrics.record_cache("capabilities_version", hit=True)
    metrics.record_cache("capabilities_version", hit=True)
    cache = metrics.snapshot()["cache"]
    assert cache["hits"] == 2
    assert cache["misses"] == 1
    assert cache["hit_ratio"] == round(2 / 3, 4)


async def test_runtime_exposes_cache_block_on_warm_calls(facade: FastMCP) -> None:
    metrics.reset()
    # Warm caches: each compact call stamps capabilities_version + data_version,
    # which are cached per release -> these record cache hits.
    await _call(facade, "get_disease", term=_ORPHA_KIF7)
    await _call(facade, "get_disease", term=_ORPHA_KIF7)
    diag = await _call(facade, "get_diagnostics")
    cache = diag["runtime"]["cache"]
    assert cache["hits"] > 0, "warm version-hash lookups must register cache hits"
    assert "hit_ratio" in cache


# --- P5.3: request_id on the error log line -----------------------------------


async def test_error_log_line_carries_request_id(
    facade: FastMCP, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = await _call(facade, "get_disease", term="ORPHA:9999999")
    request_id = result["_meta"]["request_id"]
    assert any(request_id in r.getMessage() for r in caplog.records), (
        "the structured error log must carry the same request_id as the payload"
    )
