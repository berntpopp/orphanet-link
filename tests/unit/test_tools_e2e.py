"""End-to-end tests through the registered MCP tool callables (envelope contract).

Uses the ``facade`` session fixture (backed by the real fixture SQLite database);
each tool's underlying callable (``Tool.fn``) is invoked directly so the full
envelope is exercised without HTTP/stdio transport overhead: success + _meta +
next_commands on the happy path, and a returned (not raised) error envelope on
failures.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

_ORPHA_KIF7 = "ORPHA:166024"  # present in fixtures (has KIF7 gene)
_ORPHA_58 = "ORPHA:58"  # "Alexander disease" present in fixtures


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    tools = await _tools(facade)
    return await tools[name].fn(**kwargs)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def test_get_diagnostics_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_diagnostics")
    assert result["success"] is True
    assert "_meta" in result
    assert result["_meta"].get("tool") == "get_diagnostics"
    assert isinstance(result["_meta"]["next_commands"], list)


async def test_get_server_capabilities_returns_tool_list(facade: FastMCP) -> None:
    result = await _call(facade, "get_server_capabilities")
    assert result["success"] is True
    assert "tools" in result
    assert isinstance(result["tools"], list)
    assert len(result["tools"]) >= 18
    assert isinstance(result["_meta"], dict)
    steps = result["_meta"]["next_commands"]
    assert isinstance(steps, list) and steps, "capabilities must carry a next step"


# ---------------------------------------------------------------------------
# Disease lookup
# ---------------------------------------------------------------------------


async def test_resolve_disease_by_orpha_code(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease", query=_ORPHA_KIF7)
    assert result["success"] is True
    assert result["orpha_code"] == "166024"
    assert "_meta" in result
    assert isinstance(result["_meta"]["next_commands"], list)
    # next step should be get_disease
    assert result["_meta"]["next_commands"][0]["tool"] == "get_disease"


async def test_resolve_disease_meta_source(facade: FastMCP) -> None:
    """_meta must be present, carry tool name, and have source == 'orphanet'."""
    result = await _call(facade, "resolve_disease", query=_ORPHA_58)
    assert result["success"] is True
    assert "_meta" in result
    assert result["_meta"]["source"] == "orphanet"


async def test_get_disease_meta_source(facade: FastMCP) -> None:
    """get_disease _meta must also carry source == 'orphanet'."""
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result
    assert result["_meta"]["source"] == "orphanet"


async def test_get_disease_alexander(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease", term=_ORPHA_58)
    assert result["success"] is True
    assert result["name"] is not None
    # The fixture has "Alexander disease" for ORPHA:58
    assert "alexander" in result["name"].lower()
    assert "_meta" in result


async def test_search_diseases_returns_results(facade: FastMCP) -> None:
    result = await _call(facade, "search_diseases", query="Alexander")
    assert result["success"] is True
    assert isinstance(result.get("results", []), list)
    assert "_meta" in result
    assert isinstance(result["_meta"]["next_commands"], list)


# ---------------------------------------------------------------------------
# Association tools
# ---------------------------------------------------------------------------


async def test_get_disease_genes_includes_kif7(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_genes", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result
    genes = result.get("genes", [])
    gene_symbols = [g.get("gene_symbol") for g in genes]
    assert "KIF7" in gene_symbols, f"KIF7 not found in {gene_symbols}"


async def test_get_disease_phenotypes_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_phenotypes", term=_ORPHA_58)
    assert result["success"] is True
    assert "_meta" in result
    assert "phenotypes" in result


async def test_get_disease_phenotypes_unknown_frequency_returns_invalid_input(
    facade: FastMCP,
) -> None:
    # An unrecognised frequency label must surface invalid_input + field +
    # allowed_values, not a silent count:0 (parity with the malformed-hpo_id path)
    result = await _call(facade, "get_disease_phenotypes", term=_ORPHA_58, frequency="Frequent")
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result.get("field") == "frequency"
    assert "Frequent (79-30%)" in result.get("allowed_values", [])
    assert "_meta" in result


async def test_get_disease_prevalence_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_prevalence", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result


async def test_get_disease_natural_history_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_natural_history", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result


async def test_get_disease_disability_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_disability", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result


async def test_find_diseases_by_gene_kif7(facade: FastMCP) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol="KIF7")
    assert result["success"] is True
    assert "_meta" in result
    # at least the KIF7-associated disease should appear
    results = result.get("results", [])
    orpha_codes = [r.get("orpha_code") for r in results]
    assert "166024" in orpha_codes or len(results) >= 1


async def test_find_diseases_by_phenotype_success(facade: FastMCP) -> None:
    # HP:0000256 (macrocephaly) is present in fixtures for ORPHA:58
    result = await _call(facade, "find_diseases_by_phenotype", hpo_id="HP:0000256")
    assert result["success"] is True
    assert "_meta" in result


async def test_find_diseases_by_phenotype_malformed_returns_invalid_input(facade: FastMCP) -> None:
    # A malformed hpo_id must surface invalid_input + field, not a silent empty result
    result = await _call(facade, "find_diseases_by_phenotype", hpo_id="NOT_AN_HPO_ID")
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result.get("field") == "hpo_id"
    assert "_meta" in result


# ---------------------------------------------------------------------------
# Classification / hierarchy
# ---------------------------------------------------------------------------


async def test_get_disease_classification_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_classification", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result


async def test_get_disease_ancestors_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_ancestors", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result
    assert isinstance(result["_meta"]["next_commands"], list)


async def test_get_disease_descendants_success(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_descendants", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result


# ---------------------------------------------------------------------------
# Cross-reference tools
# ---------------------------------------------------------------------------


async def test_map_cross_ontology_groups_omim(facade: FastMCP) -> None:
    result = await _call(facade, "map_cross_ontology", term=_ORPHA_KIF7)
    assert result["success"] is True
    assert "_meta" in result
    mappings = result.get("mappings", {})
    # The fixture has an OMIM cross-reference for ORPHA:166024
    assert "OMIM" in mappings, f"OMIM key missing from mappings: {list(mappings.keys())}"


async def test_resolve_xref_success(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_xref", xref_id="OMIM:607131")
    assert result["success"] is True
    assert "_meta" in result
    assert isinstance(result["_meta"]["next_commands"], list)


# ---------------------------------------------------------------------------
# Batch tools
# ---------------------------------------------------------------------------


async def test_resolve_disease_batch_success(facade: FastMCP) -> None:
    result = await _call(
        facade,
        "resolve_disease_batch",
        queries=[_ORPHA_KIF7, _ORPHA_58],
    )
    assert result["success"] is True
    assert result["count"] == 2
    for row in result["results"]:
        assert row["ok"] is True


async def test_get_disease_batch_success(facade: FastMCP) -> None:
    result = await _call(
        facade,
        "get_disease_batch",
        terms=[_ORPHA_KIF7, _ORPHA_58],
    )
    assert result["success"] is True
    assert result["count"] == 2


async def test_get_disease_batch_grounds_version_once(facade: FastMCP) -> None:
    # The batch is grounded ONCE per call, never per item: in compact (default) the
    # verbose orphanet_version string is trimmed (P1.2) and _meta.data_version anchors
    # the whole envelope; no row ever carries its own version.
    result = await _call(facade, "get_disease_batch", terms=[_ORPHA_KIF7, _ORPHA_58])
    assert result["_meta"].get("data_version"), "batch must stay grounded via _meta.data_version"
    assert "orphanet_version" not in result, "compact must trim the verbose version string"
    for row in result["results"]:
        assert "orphanet_version" not in row


async def test_resolve_disease_batch_grounds_version_once(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=[_ORPHA_KIF7, _ORPHA_58])
    assert result["_meta"].get("data_version"), "batch must stay grounded via _meta.data_version"
    assert "orphanet_version" not in result
    for row in result["results"]:
        assert "orphanet_version" not in row


# ---------------------------------------------------------------------------
# Error envelope contract
# ---------------------------------------------------------------------------


async def test_minimal_meta_carries_data_version(facade: FastMCP) -> None:
    # Observability: even the leanest (minimal) _meta anchors the data release so a
    # consumer can always tie an answer to the exact Orphanet version it came from.
    result = await _call(facade, "get_disease", term=_ORPHA_KIF7, response_mode="minimal")
    meta = result["_meta"]
    assert meta["tool"] == "get_disease"
    assert "request_id" in meta
    assert meta.get("data_version"), "minimal _meta must carry a data_version release anchor"


async def test_unknown_term_returns_error_envelope(facade: FastMCP) -> None:
    """An unknown term must return a returned-error envelope, not raise an exception."""
    result = await _call(facade, "get_disease", term="ORPHA:9999999999")
    assert result["success"] is False
    assert result["error_code"] in ("not_found", "ambiguous_query", "invalid_input")
    assert "_meta" in result
    assert isinstance(result["_meta"]["next_commands"], list)


async def test_resolve_disease_unknown_returns_error_envelope(facade: FastMCP) -> None:
    """resolve_disease with an unknown label must return an error envelope."""
    result = await _call(facade, "resolve_disease", query="__NONEXISTENT_DISEASE_XYZ__")
    assert result["success"] is False
    assert result["error_code"] in ("not_found", "ambiguous_query")
    assert "_meta" in result
