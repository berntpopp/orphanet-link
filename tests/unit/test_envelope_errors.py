"""Coverage + contract tests for the error-envelope shaping seams.

Exercises the argument-binding error builder (``build_arg_error_envelope``), the
not-found-with-suggestions and explicit-fallback recovery branches of
``_error_envelope`` (via ``run_mcp_tool``), and the search-hit snippet shaping --
paths the happy-path tests do not reach.
"""

from __future__ import annotations

from typing import Any

from orphanet_link.exceptions import NotFoundError
from orphanet_link.mcp.envelope import (
    McpErrorContext,
    McpToolError,
    build_arg_error_envelope,
    run_mcp_tool,
)
from orphanet_link.services.shaping import shape_search_hit
from tests.unit._envelope import envelope

_SIG = "get_disease(term, response_mode=, fields=)"


# --- build_arg_error_envelope (ArgValidationMiddleware's error shaper) ---------


def test_arg_error_constraints_carries_allowed_range() -> None:
    env = build_arg_error_envelope(
        tool_name="search_diseases",
        loc="limit",
        error_type="invalid_value",
        valid_params=["query", "limit", "offset"],
        signature="search_diseases(query, limit=, offset=)",
        suggestion=None,
        constraints=(["1..200"], "must be between 1 and 200"),
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "limit"
    assert env["allowed_values"] == ["1..200"]
    assert "between 1 and 200" in env["message"]
    assert env["_meta"]["next_commands"]


def test_arg_error_missing_argument() -> None:
    env = build_arg_error_envelope(
        tool_name="get_disease",
        loc="term",
        error_type="missing_argument",
        valid_params=["term", "response_mode", "fields"],
        signature=_SIG,
        suggestion=None,
    )
    assert env["error_code"] == "invalid_input"
    assert "Missing required argument" in env["message"]
    assert env["field"] == "term"
    assert env["allowed_values"] == ["term", "response_mode", "fields"]


def test_arg_error_unexpected_keyword_suggests_did_you_mean() -> None:
    env = build_arg_error_envelope(
        tool_name="get_disease",
        loc="trm",
        error_type="unexpected_keyword_argument",
        valid_params=["term", "response_mode", "fields"],
        signature=_SIG,
        suggestion="term",
    )
    assert "Unknown argument" in env["message"]
    assert "Did you mean `term`?" in env["message"]


def test_arg_error_invalid_value_without_constraints() -> None:
    env = build_arg_error_envelope(
        tool_name="get_disease",
        loc="term",
        error_type="invalid_value",
        valid_params=["term"],
        signature=_SIG,
        suggestion=None,
    )
    assert "Invalid value for argument" in env["message"]
    assert env["hint"] == _SIG


# --- _error_envelope recovery branches via run_mcp_tool -----------------------


async def test_not_found_with_suggestions_chains_to_candidates() -> None:
    async def call() -> dict[str, Any]:
        raise NotFoundError("no exact match", suggestions=[{"orpha_code": "58", "name": "A"}])

    result = envelope(
        await run_mcp_tool(
            "get_disease",
            call,
            context=McpErrorContext("get_disease", arguments={"term": "alexandr"}),
        )
    )
    assert result["error_code"] == "not_found"
    assert result["candidates"] == [{"orpha_code": "58", "name": "A"}]
    steps = result["_meta"]["next_commands"]
    assert {"tool": "get_disease", "arguments": {"term": "58"}} in steps
    assert {"tool": "search_diseases", "arguments": {"query": "alexandr"}} in steps


async def test_explicit_fallback_is_used_as_next_command() -> None:
    fallback = {"tool": "get_server_capabilities", "arguments": {}}

    async def call() -> dict[str, Any]:
        raise McpToolError(error_code="internal_error", message="kaboom")

    result = envelope(
        await run_mcp_tool(
            "get_disease",
            call,
            context=McpErrorContext("get_disease", fallback=fallback),
        )
    )
    assert result["error_code"] == "internal_error"
    assert result["_meta"]["next_commands"] == [fallback]


# --- search-hit snippet shaping ----------------------------------------------


def test_search_hit_compact_snippet_is_truncated() -> None:
    long_def = "word " * 60
    hit = {"orpha_code": "1", "name": "X", "score": 1.0, "definition": long_def}
    compact = shape_search_hit(hit, "compact")
    assert "definition" not in compact
    snippet = compact["definition_snippet"]
    assert snippet.endswith("…") and len(snippet) < len(long_def)


def test_search_hit_standard_keeps_full_definition() -> None:
    hit = {"orpha_code": "1", "name": "X", "score": 1.0, "definition": "a full definition"}
    standard = shape_search_hit(hit, "standard")
    assert standard["definition"] == "a full definition"
