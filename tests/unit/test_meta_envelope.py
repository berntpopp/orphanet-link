"""Lock the exact ``_meta`` key set per ``response_mode`` (assessment P3.2).

The MCP plane tiers ``_meta`` verbosity by ``response_mode`` to control the
per-call token tax (see ``orphanet_link/mcp/envelope.py::_shape_meta``). These
tests pin the EXACT key set each mode emits so a future change to the envelope
cannot silently widen or narrow the contract:

- ``minimal``  -> ``{tool, request_id, source, data_version}`` (lean opt-out)
- ``compact``  -> minimal PLUS ``{capabilities_version, next_commands}`` (no ``elapsed_ms``)
- ``standard`` -> compact PLUS ``{elapsed_ms}``
- ``full``     -> identical to ``standard``

The shape is proven tool-independent by re-checking the minimal/compact sets on
list/non-shaped tools (``resolve_disease``, ``search_diseases``).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

_ORPHA_KIF7 = "ORPHA:166024"  # has KIF7 gene, OMIM xref, prevalence
_ORPHA_58 = "ORPHA:58"  # "Alexander disease"

#: The exact ``_meta`` key set emitted per ``response_mode``.
_MINIMAL_META = {"tool", "request_id", "source", "data_version"}
_COMPACT_META = _MINIMAL_META | {"capabilities_version", "next_commands"}
_STANDARD_META = _COMPACT_META | {"elapsed_ms"}

_EXPECTED_BY_MODE: dict[str, set[str]] = {
    "minimal": _MINIMAL_META,
    "compact": _COMPACT_META,
    "standard": _STANDARD_META,
    "full": _STANDARD_META,
}


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return await (await _tools(facade))[name].fn(**kwargs)


# ---------------------------------------------------------------------------
# Primary tool: get_disease (the representative response_mode-aware tool)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["minimal", "compact", "standard", "full"])
async def test_get_disease_meta_key_set_is_exact_per_mode(facade: FastMCP, mode: str) -> None:
    """The ``_meta`` key set for ``get_disease`` is EXACTLY the contract for each mode."""
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode=mode)
    assert result["success"] is True
    assert set(result["_meta"].keys()) == _EXPECTED_BY_MODE[mode]


async def test_compact_meta_omits_elapsed_ms(facade: FastMCP) -> None:
    """``compact`` (the default) drops ``elapsed_ms`` from the hot path."""
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="compact")
    assert "elapsed_ms" not in result["_meta"]


async def test_standard_adds_exactly_elapsed_ms_over_compact(facade: FastMCP) -> None:
    """``standard`` is the compact set PLUS exactly ``{elapsed_ms}`` -- nothing else."""
    compact = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="compact")
    standard = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="standard")
    extra = set(standard["_meta"].keys()) - set(compact["_meta"].keys())
    assert extra == {"elapsed_ms"}


async def test_full_meta_matches_standard(facade: FastMCP) -> None:
    """``full`` carries the identical ``_meta`` key set as ``standard``."""
    standard = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="standard")
    full = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="full")
    assert set(full["_meta"].keys()) == set(standard["_meta"].keys()) == _STANDARD_META


# ---------------------------------------------------------------------------
# Lean opt-out: minimal drops guidance/cache keys; compact restores them
# ---------------------------------------------------------------------------


async def test_minimal_is_the_lean_opt_out(facade: FastMCP) -> None:
    """``minimal`` carries no ``next_commands`` and no ``capabilities_version``...

    ...but ``compact`` (the default) restores both, so ``minimal`` is the
    documented opt-out from workflow guidance + the warm-client cache key.
    """
    minimal = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="minimal")
    assert "next_commands" not in minimal["_meta"]
    assert "capabilities_version" not in minimal["_meta"]

    compact = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="compact")
    assert "next_commands" in compact["_meta"]
    assert "capabilities_version" in compact["_meta"]


# ---------------------------------------------------------------------------
# Tool-independence: the same minimal/compact shape holds for other tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("resolve_disease", {"query": _ORPHA_58}),
        ("search_diseases", {"query": "Alexander"}),
    ],
)
async def test_minimal_meta_shape_is_tool_independent(
    facade: FastMCP, name: str, kwargs: dict[str, Any]
) -> None:
    """The exact ``minimal`` ``_meta`` set holds for list/non-shaped tools too."""
    result = await _call(facade, name, response_mode="minimal", **kwargs)
    assert result["success"] is True
    assert set(result["_meta"].keys()) == _MINIMAL_META


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("resolve_disease", {"query": _ORPHA_58}),
        ("search_diseases", {"query": "Alexander"}),
    ],
)
async def test_compact_meta_shape_is_tool_independent(
    facade: FastMCP, name: str, kwargs: dict[str, Any]
) -> None:
    """The exact ``compact`` ``_meta`` set holds for list/non-shaped tools too."""
    result = await _call(facade, name, response_mode="compact", **kwargs)
    assert result["success"] is True
    assert set(result["_meta"].keys()) == _COMPACT_META
