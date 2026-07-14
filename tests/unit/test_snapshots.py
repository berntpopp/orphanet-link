"""Characterization ("snapshot") tests locking the CURRENT shape + key values.

These deterministic snapshots fix the normalized COMPACT output of each tool on
the tiny fixture disorders so a future Orphadata rebuild or a refactor surfaces
only INTENDED diffs. Volatile fields (per-call ids/timings, release versions,
build info) are stripped by ``_normalize`` before comparison.

This module covers discovery, disease lookup, and associations; the hierarchy,
cross-reference, find-by, batch, and the all-tools no-null sweep live in
``test_snapshots_more.py``. Shared harness/constants are in ``_snapshot_utils``.
"""

from __future__ import annotations

from fastmcp import FastMCP

from tests.unit._snapshot_utils import (
    _NAME_58,
    _NAME_166024,
    _OMIM_607131,
    _ORPHA_58,
    _ORPHA_166024,
    _call,
    _meta,
    _pick,
    _step,
    _subset,
)

# ---------------------------------------------------------------------------
# Discovery (stable subsets only -- build_info / version churn)
# ---------------------------------------------------------------------------


async def test_snapshot_get_server_capabilities_stable_subset(facade: FastMCP) -> None:
    result = await _call(facade, "get_server_capabilities")
    stable = _subset(
        result,
        [
            "server",
            "success",
            "tool_count",
            "tools",
            "response_modes",
            "match_types",
            "error_codes",
        ],
    )
    assert stable == {
        "server": "orphanet-link",
        "success": True,
        "tool_count": 19,
        "tools": [
            "get_server_capabilities",
            "get_diagnostics",
            "resolve_disease",
            "search_diseases",
            "get_disease",
            "get_disease_genes",
            "get_disease_phenotypes",
            "get_disease_prevalence",
            "get_disease_natural_history",
            "get_disease_disability",
            "get_disease_classification",
            "get_disease_ancestors",
            "get_disease_descendants",
            "map_cross_ontology",
            "resolve_xref",
            "find_diseases_by_gene",
            "find_diseases_by_phenotype",
            "resolve_disease_batch",
            "get_disease_batch",
        ],
        "response_modes": ["minimal", "compact", "standard", "full"],
        "match_types": ["orpha_code", "xref", "exact_label", "search"],
        "error_codes": [
            "invalid_input",
            "not_found",
            "ambiguous_query",
            "upstream_unavailable",
            "rate_limited",
            "internal",
        ],
    }


async def test_snapshot_get_diagnostics_stable_subset(facade: FastMCP) -> None:
    result = await _call(facade, "get_diagnostics")
    stable = _subset(result, ["success", "index_built", "schema_version", "disorder_count"])
    assert stable == {
        "success": True,
        "index_built": True,
        "schema_version": 1,
        "disorder_count": 2,
    }


# ---------------------------------------------------------------------------
# Disease lookup
# ---------------------------------------------------------------------------


async def test_snapshot_resolve_disease(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease", query=_ORPHA_58)
    assert result == {
        "success": True,
        "query": "ORPHA:58",
        "orpha_code": "58",
        "name": _NAME_58,
        "match_type": "orpha_code",
        "_meta": _meta("resolve_disease", [_step("get_disease", "58")]),
    }


async def test_snapshot_search_diseases(facade: FastMCP) -> None:
    result = await _call(facade, "search_diseases", query="Alexander")
    assert result == {
        "success": True,
        "query": "Alexander",
        "results": [{"orpha_code": "58", "name": _NAME_58, "score": 0.0}],
        "total": 1,
        "returned": 1,
        "limit": 25,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("search_diseases", [_step("get_disease", "58")]),
    }


async def test_snapshot_get_disease_stable_subset(facade: FastMCP) -> None:
    """Full record is large/churn-prone: lock identity + key associations only."""
    result = await _call(facade, "get_disease", term=_ORPHA_166024)
    stable = _subset(
        result,
        ["success", "orpha_code", "name", "disorder_type", "parents", "synonyms"],
    )
    assert stable == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "disorder_type": "Disease",
        # parents DEDUPED to a single entry, unique by orpha_code
        "parents": [{"orpha_code": "93419"}],
        "synonyms": ["Multiple epiphyseal dysplasia, Al-Gazali type"],
    }
    # OMIM cross-reference present and exact-match in the full xrefs block
    assert result["xrefs"]["OMIM"] == [_OMIM_607131]


# ---------------------------------------------------------------------------
# Associations
# ---------------------------------------------------------------------------


async def test_snapshot_get_disease_genes(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_genes", term=_ORPHA_166024)
    assert _subset(result, ["success", "orpha_code", "name", "count"]) == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "count": 1,
    }
    # One gene row: lock the load-bearing identity/association fields (the long tail
    # of cross-ref ids -- ensembl/swissprot/reactome/... -- is left to e2e tests).
    gene = result["genes"][0]
    assert _subset(
        gene,
        ["gene_symbol", "gene_name", "association_type", "association_status", "hgnc_id"],
    ) == {
        "gene_symbol": "KIF7",
        "gene_name": "kinesin family member 7",
        "association_type": "Disease-causing germline mutation(s) in",
        "association_status": "Assessed",
        "hgnc_id": "30497",
    }
    assert result["_meta"]["next_commands"] == [
        {"tool": "get_disease_phenotypes", "arguments": {"term": "166024"}},
        {"tool": "map_cross_ontology", "arguments": {"term": "166024"}},
    ]


async def test_snapshot_get_disease_phenotypes(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_phenotypes", term=_ORPHA_58)
    assert result == {
        "success": True,
        "orpha_code": "58",
        "name": _NAME_58,
        "count": 2,
        "phenotypes": [
            {
                "hpo_id": "HP:0000256",
                "hpo_term": "Macrocephaly",
                "frequency": "Very frequent (99-80%)",
            },
            {
                "hpo_id": "HP:0001249",
                "hpo_term": "Intellectual disability",
                "frequency": "Very frequent (99-80%)",
            },
        ],
        "_meta": _meta(
            "get_disease_phenotypes",
            [_step("get_disease_genes", "58"), _step("get_disease_prevalence", "58")],
        ),
    }


async def test_snapshot_get_disease_prevalence(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_prevalence", term=_ORPHA_166024)
    assert _subset(result, ["success", "orpha_code", "name", "count"]) == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "count": 2,
    }
    # Two rows; lock type/class/value (the prevalence_class only appears on the
    # second row -- a key shape fact -- and val_moy carries the numeric estimate).
    rows = [
        _pick(p, ["prevalence_type", "prevalence_class", "val_moy"]) for p in result["prevalence"]
    ]
    assert rows == [
        {"prevalence_type": "Cases/families", "val_moy": 4.0},
        {
            "prevalence_type": "Point prevalence",
            "prevalence_class": "<1 / 1 000 000",
            "val_moy": 0.0,
        },
    ]
    assert result["_meta"]["next_commands"] == [
        {"tool": "get_disease", "arguments": {"term": "166024"}}
    ]


async def test_snapshot_get_disease_natural_history(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_natural_history", term=_ORPHA_166024)
    assert result == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "age_of_onset": [{"onset": "Infancy"}, {"onset": "Neonatal"}],
        "inheritance": [{"inheritance": "Autosomal recessive"}],
        "_meta": _meta("get_disease_natural_history", [_step("get_disease", "166024")]),
    }


async def test_snapshot_get_disease_disability(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_disability", term=_ORPHA_166024)
    assert result == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "count": 0,
        "coverage": "none",
        "_meta": _meta("get_disease_disability", [_step("get_disease", "166024")]),
    }
