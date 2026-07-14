"""Contract: every tool's real output validates against its own ``output_schema``.

AGENTS.md states: *"Every tool's real output (success + error, all response modes)
must validate against its own output_schema -- enforced by
tests/unit/test_output_schemas.py."* This module enforces that invariant.

The schemas live in :mod:`orphanet_link.mcp.schemas` and are attached to each tool
via the ``output_schema=`` argument of ``@mcp.tool``. FastMCP exposes the registered
schema verbatim on ``Tool.output_schema`` (a plain JSON Schema ``dict``), so this
module validates against ``tool.output_schema`` directly -- the authoritative,
as-registered contract -- rather than re-importing the constants from
:mod:`schemas`.

Three guarantees are checked:

1. Every tool's SUCCESS output validates -- across all four ``response_mode`` values
   for tools that accept it (and the single result for those that do not).
2. Every error-capable tool's returned (not raised) error ENVELOPE validates against
   the SAME schema (the permissive schemas admit both success and error shapes).
3. A coverage guard fails if a newly-registered tool has no success-args mapping, so
   the test self-maintains as the tool surface grows.
"""

from __future__ import annotations

from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest
from fastmcp import FastMCP

from tests.unit._envelope import envelope

# Fixture disorders (present in the tiny test database built by conftest._build_db):
#   ORPHA:166024 -> KIF7-associated disease, xref OMIM:607131
#   ORPHA:58     -> "Alexander disease", phenotype HP:0000256
# Classification tree present in fixtures: 156 -> 93419 -> 166024.
_ORPHA_KIF7 = "ORPHA:166024"
_ORPHA_58 = "ORPHA:58"
_OMIM_KIF7 = "OMIM:607131"
_HPO_ALEXANDER = "HP:0000256"

_RESPONSE_MODES = ("minimal", "compact", "standard", "full")

#: Valid success kwargs per tool name (excluding ``response_mode``, which the success
#: test sweeps separately). Every registered tool MUST appear here -- the coverage
#: guard (``test_every_tool_has_success_args``) fails otherwise, so a newly-added tool
#: without a mapping breaks the build until it is given representative args.
_SUCCESS_ARGS: dict[str, dict[str, Any]] = {
    # discovery (no response_mode)
    "get_server_capabilities": {},
    "get_diagnostics": {},
    # disease lookup / search
    "resolve_disease": {"query": _ORPHA_58},
    "search_diseases": {"query": "Alexander"},
    "get_disease": {"term": _ORPHA_KIF7},
    # associations
    "get_disease_genes": {"term": _ORPHA_KIF7},
    "get_disease_phenotypes": {"term": _ORPHA_58},
    "get_disease_prevalence": {"term": _ORPHA_KIF7},
    "get_disease_natural_history": {"term": _ORPHA_KIF7},
    "get_disease_disability": {"term": _ORPHA_KIF7},
    # classification / hierarchy
    "get_disease_classification": {"term": _ORPHA_KIF7},
    "get_disease_ancestors": {"term": _ORPHA_KIF7},
    "get_disease_descendants": {"term": _ORPHA_KIF7},
    # cross-ontology
    "map_cross_ontology": {"term": _ORPHA_KIF7},
    "resolve_xref": {"xref_id": _OMIM_KIF7},
    # find-by
    "find_diseases_by_gene": {"gene_symbol": "KIF7"},
    "find_diseases_by_phenotype": {"hpo_id": _HPO_ALEXANDER},
    # batch
    "resolve_disease_batch": {"queries": [_ORPHA_58, _ORPHA_KIF7]},
    "get_disease_batch": {"terms": [_ORPHA_58, _ORPHA_KIF7]},
}

#: Tools that accept a ``response_mode`` argument (swept across all four values).
#: The two discovery tools do not, so they are validated once.
_NO_RESPONSE_MODE = {"get_server_capabilities", "get_diagnostics"}

#: A representative error trigger per error-capable tool: kwargs that drive a
#: returned (not raised) error envelope, plus the ``error_code`` it must report.
#: Validating these proves the SAME permissive schema admits the error shape too.
_ERROR_CASES: dict[str, dict[str, Any]] = {
    "get_disease": {
        "kwargs": {"term": "ORPHA:9999999"},
        "error_code": "not_found",
    },
    "resolve_disease": {
        "kwargs": {"query": "__no_such_disease_xyz__"},
        "error_code": "not_found",
    },
    "get_disease_genes": {
        "kwargs": {"term": "ORPHA:9999999"},
        "error_code": "not_found",
    },
    "get_disease_phenotypes": {
        "kwargs": {"term": "ORPHA:9999999"},
        "error_code": "not_found",
    },
    "get_disease_disability": {
        "kwargs": {"term": "ORPHA:9999999"},
        "error_code": "not_found",
    },
    "map_cross_ontology": {
        "kwargs": {"term": "ORPHA:9999999"},
        "error_code": "not_found",
    },
    "get_disease_ancestors": {
        "kwargs": {"term": "__no_such_disease_xyz__"},
        "error_code": "not_found",
    },
    "resolve_xref": {
        "kwargs": {"xref_id": "notacurie"},
        "error_code": "invalid_input",
    },
    "find_diseases_by_gene": {
        "kwargs": {"gene_symbol": " "},
        "error_code": "invalid_input",
    },
    "find_diseases_by_phenotype": {
        "kwargs": {"hpo_id": "NOT_AN_HPO_ID"},
        "error_code": "invalid_input",
    },
    "get_disease_batch": {
        "kwargs": {"terms": [_ORPHA_58] * 51},
        "error_code": "invalid_input",
    },
    "resolve_disease_batch": {
        "kwargs": {"queries": []},
        "error_code": "invalid_input",
    },
}


async def _tools(facade: FastMCP) -> dict[str, Any]:
    """Map tool name -> live ``Tool`` object (carrying ``.fn`` and ``.output_schema``)."""
    return {t.name: t for t in await facade.list_tools()}


def _validate(result: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate ``result`` against ``schema``; raise a readable AssertionError on failure."""
    assert isinstance(schema, dict), "tool.output_schema must be a JSON Schema dict"
    jsonschema.validate(instance=result, schema=schema)


# ---------------------------------------------------------------------------
# 0. Sanity: tool.output_schema is a usable JSON Schema (chosen validation source)
# ---------------------------------------------------------------------------


async def test_output_schema_is_usable_json_schema(facade: FastMCP) -> None:
    """Every tool exposes a non-empty, well-formed JSON Schema on ``output_schema``."""
    tools = await _tools(facade)
    assert tools, "facade registered no tools"
    for name, tool in tools.items():
        schema = tool.output_schema
        assert isinstance(schema, dict) and schema, f"{name}: output_schema is not a dict"
        # A malformed schema makes Draft202012Validator.check_schema raise.
        jsonschema.Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# 1. Success output validates across all response modes
# ---------------------------------------------------------------------------


async def test_success_output_validates_all_modes(facade: FastMCP) -> None:
    """Every tool's success output validates against its own output_schema in every mode."""
    tools = await _tools(facade)
    for name, base_kwargs in _SUCCESS_ARGS.items():
        assert name in tools, f"args mapping references unknown tool {name!r}"
        tool = tools[name]
        modes = (None,) if name in _NO_RESPONSE_MODE else _RESPONSE_MODES
        for mode in modes:
            kwargs = dict(base_kwargs)
            if mode is not None:
                kwargs["response_mode"] = mode
            result = envelope(await tool.fn(**kwargs))
            label = name if mode is None else f"{name}[{mode}]"
            assert result.get("success") is True, f"{label}: expected success, got {result!r}"
            try:
                _validate(result, tool.output_schema)
            except jsonschema.ValidationError as exc:  # pragma: no cover - contract bug
                pytest.fail(f"{label}: success output failed its output_schema: {exc.message}")


# ---------------------------------------------------------------------------
# 2. Error envelope validates against the SAME schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(_ERROR_CASES))
async def test_error_envelope_validates(facade: FastMCP, tool_name: str) -> None:
    """A returned (not raised) error envelope validates against the tool's own schema."""
    tools = await _tools(facade)
    assert tool_name in tools, f"error case references unknown tool {tool_name!r}"
    tool = tools[tool_name]
    case = _ERROR_CASES[tool_name]
    result = envelope(await tool.fn(**case["kwargs"]))
    assert result.get("success") is False, (
        f"{tool_name}: expected an error envelope, got {result!r}"
    )
    assert result.get("error_code") == case["error_code"], (
        f"{tool_name}: expected error_code={case['error_code']!r}, got {result.get('error_code')!r}"
    )
    try:
        _validate(result, tool.output_schema)
    except jsonschema.ValidationError as exc:  # pragma: no cover - contract bug
        pytest.fail(f"{tool_name}: error envelope failed its output_schema: {exc.message}")


# ---------------------------------------------------------------------------
# 3. Coverage guard: the args map must cover exactly the registered tool set
# ---------------------------------------------------------------------------


async def test_every_tool_has_success_args(facade: FastMCP) -> None:
    """The success-args mapping must cover exactly the live tool set (self-maintaining)."""
    registered = set(await _tools(facade))
    mapped = set(_SUCCESS_ARGS)
    missing = registered - mapped
    extra = mapped - registered
    assert not missing, f"tools registered without success-args coverage: {sorted(missing)}"
    assert not extra, f"success-args mapping references non-existent tools: {sorted(extra)}"
    assert mapped == registered
