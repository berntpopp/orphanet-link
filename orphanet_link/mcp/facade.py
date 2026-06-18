"""MCP facade for orphanet-link: assemble the FastMCP instance with all tools."""

from __future__ import annotations

from fastmcp import FastMCP

from orphanet_link.mcp.capabilities import register_capability_resources
from orphanet_link.mcp.middleware import ArgValidationMiddleware
from orphanet_link.mcp.resources import ORPHANET_SERVER_INSTRUCTIONS
from orphanet_link.mcp.tools import (
    register_association_tools,
    register_batch_tools,
    register_classification_tools,
    register_discovery_tools,
    register_disease_tools,
    register_xref_tools,
)


def create_orphanet_mcp() -> FastMCP:
    """Build a FastMCP instance with all orphanet-link tools, resources, middleware."""
    mcp = FastMCP(
        name="orphanet-link",
        instructions=ORPHANET_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_disease_tools(mcp)
    register_association_tools(mcp)
    register_classification_tools(mcp)
    register_xref_tools(mcp)
    register_batch_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
