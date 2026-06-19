"""Snapshot characterization tests, part 2: hierarchy, cross-reference, find-by,
batch, and the all-tools no-null sweep.

Companion to ``test_snapshots.py`` (discovery / lookup / associations). Shared
harness + constants live in ``_snapshot_utils``. Split from one module to stay
within the 500-line-per-file budget.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from tests.unit._snapshot_utils import (
    _NAME_58,
    _NAME_166024,
    _OMIM_607131,
    _ORPHA_58,
    _ORPHA_166024,
    _call,
    _has_null,
    _meta,
    _step,
    _subset,
)

# ---------------------------------------------------------------------------
# Hierarchy / classification
# ---------------------------------------------------------------------------


async def test_snapshot_get_disease_classification(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_classification", term=_ORPHA_166024)
    # Load-bearing invariant: parents are DEDUPED to a single entry, unique by
    # orpha_code, with no null leaf fields (compact drops a null name recursively).
    assert result["parents"] == [{"orpha_code": "93419"}]
    assert result == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "parents": [{"orpha_code": "93419"}],
        "_meta": _meta("get_disease_classification", [_step("get_disease_ancestors", "166024")]),
    }


async def test_snapshot_get_disease_ancestors(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_ancestors", term=_ORPHA_166024)
    # ancestors 156 + 93419 are classification-only nodes (no disorder row -> name
    # is NULL/dropped), so ORDER BY d.name leaves their relative order undefined;
    # snapshot the closure SET, the stable invariant, not the row order.
    ancestors = result.pop("ancestors")
    assert sorted(ancestors, key=lambda r: r["orpha_code"]) == [
        {"orpha_code": "156"},
        {"orpha_code": "93419"},
    ]
    assert result == {
        "success": True,
        "orpha_code": "166024",
        "name": _NAME_166024,
        "total": 2,
        "returned": 2,
        "limit": 200,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("get_disease_ancestors", [_step("get_disease_descendants", "166024")]),
    }


async def test_snapshot_get_disease_descendants(facade: FastMCP) -> None:
    result = await _call(facade, "get_disease_descendants", term="ORPHA:156")
    # descendants closure is order-independent (see ancestors); snapshot the SET.
    descendants = result.pop("descendants")
    assert sorted(descendants, key=lambda r: r["orpha_code"]) == [
        {
            "orpha_code": "166024",
            "name": _NAME_166024,
        },
        {"orpha_code": "93419"},
    ]
    assert result == {
        "success": True,
        "orpha_code": "156",
        "total": 2,
        "returned": 2,
        "limit": 200,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("get_disease_descendants", [_step("get_disease_ancestors", "156")]),
    }


# ---------------------------------------------------------------------------
# Cross-reference
# ---------------------------------------------------------------------------


async def test_snapshot_map_cross_ontology(facade: FastMCP) -> None:
    result = await _call(facade, "map_cross_ontology", term=_ORPHA_166024)
    assert result["count"] == 5
    assert result["mappings"]["OMIM"] == [_OMIM_607131]
    assert result["mappings"]["MONDO"] == [
        {"object_id": "0011778", "mapping_relation": "E", "validation_status": "Validated"}
    ]
    assert sorted(result["mappings"]) == ["ICD-10", "ICD-11", "MONDO", "OMIM", "UMLS"]
    assert result["_meta"] == {
        "source": "orphanet",
        "tool": "map_cross_ontology",
        "next_commands": [
            {"tool": "get_disease_ancestors", "arguments": {"term": "166024"}},
            {"tool": "get_disease", "arguments": {"term": "166024"}},
        ],
    }


async def test_snapshot_resolve_xref(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_xref", xref_id="OMIM:607131")
    assert result == {
        "success": True,
        "xref_id": "OMIM:607131",
        "source": "OMIM",
        "object_id": "607131",
        "matches": [
            {
                "orpha_code": "166024",
                "name": _NAME_166024,
            }
        ],
        "total": 1,
        "returned": 1,
        "limit": 50,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("resolve_xref", [_step("get_disease", "166024")]),
    }


# ---------------------------------------------------------------------------
# Find-by
# ---------------------------------------------------------------------------


async def test_snapshot_find_diseases_by_gene(facade: FastMCP) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol="KIF7")
    assert result == {
        "success": True,
        "gene_symbol": "KIF7",
        "results": [
            {
                "orpha_code": "166024",
                "name": _NAME_166024,
            }
        ],
        "total": 1,
        "returned": 1,
        "limit": 50,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("find_diseases_by_gene", [_step("get_disease", "166024")]),
    }


async def test_snapshot_find_diseases_by_phenotype(facade: FastMCP) -> None:
    result = await _call(facade, "find_diseases_by_phenotype", hpo_id="HP:0000256")
    assert result == {
        "success": True,
        "hpo_id": "HP:0000256",
        "results": [{"orpha_code": "58", "name": _NAME_58}],
        "total": 1,
        "returned": 1,
        "limit": 50,
        "offset": 0,
        "truncated": False,
        "_meta": _meta("find_diseases_by_phenotype", [_step("get_disease", "58")]),
    }


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


async def test_snapshot_resolve_disease_batch(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=[_ORPHA_58, _ORPHA_166024])
    assert result == {
        "success": True,
        "count": 2,
        "results": [
            {
                "ok": True,
                "query": "ORPHA:58",
                "orpha_code": "58",
                "name": _NAME_58,
                "match_type": "orpha_code",
            },
            {
                "ok": True,
                "query": "ORPHA:166024",
                "orpha_code": "166024",
                "name": _NAME_166024,
                "match_type": "orpha_code",
            },
        ],
        "_meta": _meta("resolve_disease_batch", [_step("get_disease", "58")]),
    }


async def test_snapshot_get_disease_batch_stable_subset(facade: FastMCP) -> None:
    """Batch records mirror the full get_disease record: lock identity per row."""
    result = await _call(facade, "get_disease_batch", terms=[_ORPHA_58, _ORPHA_166024])
    assert result["success"] is True
    assert result["count"] == 2
    rows = [_subset(r, ["ok", "term", "orpha_code", "name"]) for r in result["results"]]
    assert rows == [
        {"ok": True, "term": "ORPHA:58", "orpha_code": "58", "name": _NAME_58},
        {
            "ok": True,
            "term": "ORPHA:166024",
            "orpha_code": "166024",
            "name": _NAME_166024,
        },
    ]
    # F4: version grounded once at the top level, never echoed per item (it was
    # stripped by the normalizer, so just assert no row leaked it).
    for row in result["results"]:
        assert "orphanet_version" not in row


# ---------------------------------------------------------------------------
# Invariant: compact output is NEVER null anywhere (locks the F4 null-drop)
# ---------------------------------------------------------------------------

#: One representative compact call per tool, sweeping all 19.
_SWEEP: list[tuple[str, dict[str, Any]]] = [
    ("get_server_capabilities", {}),
    ("get_diagnostics", {}),
    ("resolve_disease", {"query": _ORPHA_58}),
    ("search_diseases", {"query": "Alexander"}),
    ("get_disease", {"term": _ORPHA_166024}),
    ("get_disease_genes", {"term": _ORPHA_166024}),
    ("get_disease_phenotypes", {"term": _ORPHA_58}),
    ("get_disease_prevalence", {"term": _ORPHA_166024}),
    ("get_disease_natural_history", {"term": _ORPHA_166024}),
    ("get_disease_disability", {"term": _ORPHA_166024}),
    ("get_disease_classification", {"term": _ORPHA_166024}),
    ("get_disease_ancestors", {"term": _ORPHA_166024}),
    ("get_disease_descendants", {"term": "ORPHA:156"}),
    ("map_cross_ontology", {"term": _ORPHA_166024}),
    ("resolve_xref", {"xref_id": "OMIM:607131"}),
    ("find_diseases_by_gene", {"gene_symbol": "KIF7"}),
    ("find_diseases_by_phenotype", {"hpo_id": "HP:0000256"}),
    ("resolve_disease_batch", {"queries": [_ORPHA_58, _ORPHA_166024]}),
    ("get_disease_batch", {"terms": [_ORPHA_58, _ORPHA_166024]}),
]


async def test_compact_outputs_contain_no_nulls_anywhere(facade: FastMCP) -> None:
    """Sweep all 19 tools: NO null value may appear anywhere in compact output.

    The ``get_diagnostics`` runtime block reports ``error_rate: null`` before any
    error is sampled; that telemetry field is excluded from the contract under
    test (the F4 null-drop applies to domain payloads, not the diagnostics
    runtime counters). Every other tool must be null-free, recursively.
    """
    assert len(_SWEEP) == 19
    for name, kwargs in _SWEEP:
        result = await _call(facade, name, **kwargs)
        if name == "get_diagnostics":
            result = {k: v for k, v in result.items() if k != "runtime"}
        assert not _has_null(result), f"{name} compact output leaked a null value"
