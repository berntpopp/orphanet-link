"""Locks the ratified GeneFoundry Response-Envelope Standard v1 (flat banner)
at this backend's MCP wrapper boundary (``orphanet_link.mcp.envelope.run_mcp_tool``).
Adapted from clingen-link (the fleet reference, PR #20). SUCCESS ->
``{success, results|result, _meta}``; FAILURE -> flat
``{success: False, error_code, message, retryable, recovery_action, _meta}``.

Fleet disclaimer standardization (2026-07-03): ``_meta`` now stamps
``unsafe_for_clinical_use: True`` on every call, success and error alike, at every
``response_mode`` -- ``tests/unit/test_meta_envelope.py`` pins the exact per-mode
``_meta`` key set and now includes it. This closes the drift previously documented
here (the disclaimer used to live only in the static ``get_server_capabilities``
text, not per-call).
"""

from __future__ import annotations

from orphanet_link.exceptions import NotFoundError
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from tests.unit._envelope import envelope


async def test_success_envelope_matches_response_envelope_standard_v1() -> None:
    async def call() -> dict[str, object]:
        return {"results": [{"id": "x"}]}

    result = envelope(await run_mcp_tool("get_disease", call))
    assert result["success"] is True
    assert result["results"] == [{"id": "x"}]
    assert result["_meta"]["tool"] == "get_disease"
    assert result["_meta"]["unsafe_for_clinical_use"] is True


async def test_single_item_result_key_is_preserved() -> None:
    async def call() -> dict[str, object]:
        return {"result": {"id": "x"}}

    result = envelope(await run_mcp_tool("get_disease", call))
    assert result["success"] is True
    assert result["result"] == {"id": "x"}


async def test_error_envelope_is_flat_not_a_bare_exception() -> None:
    async def call() -> dict[str, object]:
        raise NotFoundError("not found")

    result = envelope(
        await run_mcp_tool("get_disease", call, context=McpErrorContext(tool_name="get_disease"))
    )
    assert result["success"] is False
    assert isinstance(result["error_code"], str) and result["error_code"]
    assert isinstance(result["message"], str) and result["message"]
    assert isinstance(result["retryable"], bool)
    assert isinstance(result["recovery_action"], str)
    assert "error" not in result  # flat, not nested
    assert result["_meta"]["tool"] == "get_disease"
    assert result["_meta"]["unsafe_for_clinical_use"] is True
