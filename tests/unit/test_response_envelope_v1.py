"""Locks the ratified GeneFoundry Response-Envelope Standard v1 (flat banner)
at this backend's MCP wrapper boundary (``orphanet_link.mcp.envelope.run_mcp_tool``).
Adapted from clingen-link (the fleet reference, PR #20). SUCCESS ->
``{success, results|result, _meta}``; FAILURE -> flat
``{success: False, error_code, message, retryable, recovery_action, _meta}``.

GROUND-TRUTH NOTE: unlike clingen/panelapp/gtex, orphanet-link's ``_meta`` does
NOT stamp ``unsafe_for_clinical_use`` on any path or ``response_mode`` --
``tests/unit/test_meta_envelope.py`` already pins the exact per-mode ``_meta``
key set and none of them include it (the disclaimer currently lives only in
the static ``get_server_capabilities`` text, not per-call). This test locks
that real behaviour instead of fabricating conformance; see the
Response-Envelope Standard v1 doc -- closing this gap is tracked as fleet
drift, not fixed here (test-only change, no behaviour change).
"""

from __future__ import annotations

from orphanet_link.exceptions import NotFoundError
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool


async def test_success_envelope_matches_response_envelope_standard_v1() -> None:
    async def call() -> dict[str, object]:
        return {"results": [{"id": "x"}]}

    result = await run_mcp_tool("get_disease", call)
    assert result["success"] is True
    assert result["results"] == [{"id": "x"}]
    assert result["_meta"]["tool"] == "get_disease"
    # DRIFT (see module docstring): no unsafe_for_clinical_use in per-call _meta.
    assert "unsafe_for_clinical_use" not in result["_meta"]


async def test_single_item_result_key_is_preserved() -> None:
    async def call() -> dict[str, object]:
        return {"result": {"id": "x"}}

    result = await run_mcp_tool("get_disease", call)
    assert result["success"] is True
    assert result["result"] == {"id": "x"}


async def test_error_envelope_is_flat_not_a_bare_exception() -> None:
    async def call() -> dict[str, object]:
        raise NotFoundError("not found")

    result = await run_mcp_tool(
        "get_disease", call, context=McpErrorContext(tool_name="get_disease")
    )
    assert result["success"] is False
    assert isinstance(result["error_code"], str) and result["error_code"]
    assert isinstance(result["message"], str) and result["message"]
    assert isinstance(result["retryable"], bool)
    assert isinstance(result["recovery_action"], str)
    assert "error" not in result  # flat, not nested
    assert result["_meta"]["tool"] == "get_disease"
    # DRIFT (see module docstring): no unsafe_for_clinical_use in per-call _meta.
    assert "unsafe_for_clinical_use" not in result["_meta"]
