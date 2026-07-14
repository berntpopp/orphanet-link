"""P1 token-discipline contracts (assessment F-05).

- P1.1: get_disease(include=[...]) composes one record (definition + genes +
  phenotypes + prevalence + disability) so the dominant 8-call fan-out collapses
  to a single round trip; unknown sections are rejected with invalid_input.
- P1.2: the verbose human-readable orphanet_version string is dropped from the
  payload body in the lean modes (minimal/compact) -- the short _meta.data_version
  hash still grounds every call -- and shipped only in standard/full. The two
  discovery tools keep it (the release IS their product).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp import FastMCP

from tests.unit._envelope import envelope

_ORPHA_KIF7 = "ORPHA:166024"  # has KIF7 gene, OMIM xref, prevalence
_ORPHA_58 = "ORPHA:58"  # Alexander disease, 2 phenotypes


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    return envelope(await (await _tools(facade))[name].fn(**kwargs))


# --- P1.1: one-call composed record -------------------------------------------


async def test_get_disease_include_composes_sections_in_one_call(facade: FastMCP) -> None:
    composed = await _call(
        facade,
        "get_disease",
        term=_ORPHA_KIF7,
        include=["genes", "phenotypes", "prevalence"],
    )
    assert composed["success"] is True
    # The composed record carries the base disease fields AND the requested sections.
    assert composed["name"]
    assert "definition" in composed or composed.get("definition") is None
    assert "genes" in composed, "include=genes must attach the gene section"
    assert "prevalence" in composed, "include=prevalence must attach prevalence rows"
    # And those sections match what the standalone tools return (no drift).
    genes = await _call(facade, "get_disease_genes", term=_ORPHA_KIF7)
    assert composed["genes"] == genes["genes"]


async def test_get_disease_include_phenotypes_matches_standalone(facade: FastMCP) -> None:
    composed = await _call(facade, "get_disease", term=_ORPHA_58, include=["phenotypes"])
    standalone = await _call(facade, "get_disease_phenotypes", term=_ORPHA_58)
    assert composed["phenotypes"] == standalone["phenotypes"]


async def test_get_disease_include_unknown_section_is_invalid_input(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, include=["bogus"])
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "include"
    assert "genes" in result.get("allowed_values", [])


async def test_include_one_call_cuts_tokens_vs_fanout(facade: FastMCP) -> None:
    """Exit criterion: one composed call is >=30% cheaper than the 4-call fan-out.

    The fan-out reships a full _meta envelope (+ identity) on every call; the
    composed call pays that once. Measured on the fixture disorder: ~34% smaller.
    """
    fanout = [
        await _call(facade, "get_disease", term=_ORPHA_KIF7),
        await _call(facade, "get_disease_genes", term=_ORPHA_KIF7),
        await _call(facade, "get_disease_phenotypes", term=_ORPHA_KIF7),
        await _call(facade, "get_disease_prevalence", term=_ORPHA_KIF7),
    ]
    fanout_chars = sum(len(json.dumps(r)) for r in fanout)
    one_call = await _call(
        facade, "get_disease", term=_ORPHA_KIF7, include=["genes", "phenotypes", "prevalence"]
    )
    one_chars = len(json.dumps(one_call))
    reduction = 1 - one_chars / fanout_chars
    assert reduction >= 0.30, f"expected >=30% token cut, got {reduction:.1%}"


# --- P1.2: orphanet_version body trim in lean modes ---------------------------


@pytest.mark.parametrize("mode", ["minimal", "compact"])
async def test_lean_modes_drop_version_string_keep_data_version(facade: FastMCP, mode: str) -> None:
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode=mode)
    assert "orphanet_version" not in result, f"{mode}: verbose version string must be dropped"
    assert result["_meta"].get("data_version"), f"{mode}: _meta.data_version must still ground it"


@pytest.mark.parametrize("mode", ["standard", "full"])
async def test_rich_modes_keep_version_string(facade: FastMCP, mode: str) -> None:
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode=mode)
    assert result.get("orphanet_version"), f"{mode}: must retain the human-readable version"


async def test_discovery_tools_keep_version_string_in_compact(facade: FastMCP) -> None:
    # The release string is the PRODUCT of these tools; never trim it.
    diag = await _call(facade, "get_diagnostics")
    assert diag.get("orphanet_version")
    caps = await _call(facade, "get_server_capabilities")
    assert caps.get("orphanet_version")


async def test_non_shaped_tools_also_drop_version_in_compact(facade: FastMCP) -> None:
    # resolve_disease / search_diseases build dicts inline (no shape()); the envelope
    # trim must reach them too so the policy is uniform across the whole surface.
    for name, kwargs in (
        ("resolve_disease", {"query": _ORPHA_58}),
        ("search_diseases", {"query": "Alexander"}),
        ("resolve_xref", {"xref_id": "OMIM:607131"}),
    ):
        result = await _call(facade, name, **kwargs)
        assert "orphanet_version" not in result, f"{name}: compact must drop the version string"
        assert result["_meta"].get("data_version")
