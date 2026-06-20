"""P0 quick-win contracts (assessment F-02 / F-03 / F-04).

- F-02: the two context-free discovery tools must NOT emit a canned, concrete
  disease label in ``_meta.next_commands`` (it reads as fabricated data); they
  use a generic placeholder instead, while still carrying a non-empty step so
  the universal ``next_commands`` invariant holds.
- F-03: ``count`` semantics (leaf rows, not groups) are documented in the
  docstrings of the grouped-payload tools.
- F-04: ``get_disease_disability`` distinguishes "no annotation" (``coverage:
  'none'``) from an error, so an agent never reads empty as failure.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from orphanet_link.mcp.next_commands import DISCOVERY_PLACEHOLDER_QUERY
from orphanet_link.services.orphanet_service import OrphanetService

_ORPHA_166024 = "ORPHA:166024"  # fixture disorder with NO disability annotation


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return await (await _tools(facade))[name].fn(**kwargs)


def _arg_strings(steps: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for step in steps:
        for value in (step.get("arguments") or {}).values():
            if isinstance(value, str):
                out.append(value)
    return out


# --- F-02: no canned disease label on the context-free discovery tools -------


async def test_discovery_tools_emit_no_canned_disease_label(facade: FastMCP) -> None:
    for tool in ("get_server_capabilities", "get_diagnostics"):
        result = await _call(facade, tool)
        steps = result["_meta"]["next_commands"]
        assert isinstance(steps, list) and steps, f"{tool}: next_commands must stay non-empty"
        args = _arg_strings(steps)
        # The prior canned example was the concrete label "Aicardi syndrome".
        assert not any("aicardi" in a.lower() for a in args), f"{tool}: leaked canned label {args}"
        # Any query arg present must be the generic, self-evident placeholder.
        assert all(a == DISCOVERY_PLACEHOLDER_QUERY for a in args), (
            f"{tool}: non-placeholder disease arg in {args}"
        )


def test_discovery_placeholder_is_an_obvious_template() -> None:
    # Bracketed -> clearly a fill-in template, not a real Orphanet answer.
    assert "<" in DISCOVERY_PLACEHOLDER_QUERY and ">" in DISCOVERY_PLACEHOLDER_QUERY


# --- F-03: count = leaf rows (not groups) is documented ------------------------


async def test_count_semantics_documented_on_grouped_tools(facade: FastMCP) -> None:
    tools = await _tools(facade)
    for name in ("map_cross_ontology", "get_disease_genes"):
        description = tools[name].description or ""
        assert "leaf" in description.lower(), f"{name}: count=leaf-rows semantics not documented"


# --- F-04: disability coverage marker -----------------------------------------


async def test_disability_coverage_none_when_unannotated(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_disability", term=_ORPHA_166024)
    assert result["success"] is True
    assert result["count"] == 0
    assert result["coverage"] == "none", (
        "empty disability must be marked coverage='none', not error"
    )


def test_disability_coverage_present_when_annotated() -> None:
    """A disorder WITH a functional-consequence row is marked coverage='present'."""

    class _StubRepo:
        def get_disorder(self, code: str) -> dict[str, Any]:
            return {"name": "Stub disorder"}

        def get_disability(self, code: str) -> list[dict[str, Any]]:
            return [{"disability": "Managing one's health", "frequency": "Very frequent"}]

        def get_meta(self) -> dict[str, Any]:
            return {"orphanet_version": "1.3.42"}

    svc = OrphanetService(repo=_StubRepo())
    result = svc.get_disease_disability("ORPHA:1")
    assert result["count"] == 1
    assert result["coverage"] == "present"
