"""Discovery tools: get_server_capabilities, get_diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from orphanet_link.buildinfo import build_info
from orphanet_link.mcp import metrics
from orphanet_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from orphanet_link.mcp.capabilities import collect_tool_signatures, project_capabilities
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.next_commands import DISCOVERY_PLACEHOLDER_QUERY, after_capabilities, cmd
from orphanet_link.mcp.service_adapters import get_orphanet_service
from orphanet_link.mcp.tools._common import ToolReturn

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register the discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B2 (see tools/__init__.py)
        tags={"discovery"},
        description=(
            "Return the orphanet-link discovery surface: identity/build/Orphanet release, "
            "the tool list WITH call signatures, response modes, recommended "
            "workflows, the cross-reference source ranking, the error taxonomy, and "
            "limits. detail='full' adds the full policy notes. Call this first in a "
            "cold session, or read orphanet://tools / orphanet://capabilities. "
            "Signature: get_server_capabilities(detail=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds policy notes)."),
        ] = "summary",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            signatures = await collect_tool_signatures(mcp)
            payload = project_capabilities(detail, signatures)
            payload.setdefault("_meta", {})["next_commands"] = after_capabilities()
            return payload

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities", keep_version=True),
        )

    @mcp.tool(
        name="get_diagnostics",
        title="Get Orphanet Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B2 (see tools/__init__.py)
        tags={"discovery"},
        description=(
            "Report the local Orphanet index status: whether the data is built, the "
            "loaded Orphanet release version, disorder counts, schema version, and when "
            "it was built, plus a runtime block (request/error counts, latency "
            "percentiles p50/p95/p99, a response_mode distribution that surfaces "
            "over-fetch, and a version-hash cache hit/miss ratio). Use this to confirm "
            "freshness or diagnose a data_unavailable error. "
            "Signature: get_diagnostics()."
        ),
    )
    async def get_diagnostics() -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_diagnostics()
            payload["build"] = build_info()
            payload["runtime"] = metrics.snapshot()
            payload.setdefault("_meta", {})["next_commands"] = (
                [cmd("resolve_disease", query=DISCOVERY_PLACEHOLDER_QUERY)]
                if payload.get("index_built")
                else [cmd("get_server_capabilities")]
            )
            return payload

        return await run_mcp_tool(
            "get_diagnostics",
            call,
            context=McpErrorContext("get_diagnostics", keep_version=True),
        )
