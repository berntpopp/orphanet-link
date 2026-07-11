"""MCP facade for orphanet-link: assemble the FastMCP instance with all tools."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from orphanet_link import __version__
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

#: FastMCP's tool dispatcher logs the full pydantic error list (which embeds the
#: caller's argument values) and a raw traceback BEFORE ArgValidationMiddleware
#: reshapes the failure. Those records bypass every caller-facing sanitizer, so we
#: neutralise them at the log sink (the caller still gets the sanitized envelope).
_FASTMCP_TOOL_LOGGER = "fastmcp.server.server"
_SCRUB_PREFIXES = ("Invalid arguments for tool", "Error calling tool")


class _ToolErrorLogScrubber(logging.Filter):
    """Drop caller input / raw exception detail from FastMCP tool-dispatch error logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if str(record.msg).startswith(_SCRUB_PREFIXES):
            record.msg = "%s"
            record.args = ("orphanet-link: tool call failed (detail withheld; see error envelope)",)
            record.exc_info = None
            record.exc_text = None
        return True


def _install_tool_error_log_scrubber() -> None:
    """Attach the scrubber to FastMCP's tool logger once (idempotent across facades)."""
    fastmcp_logger = logging.getLogger(_FASTMCP_TOOL_LOGGER)
    if not any(isinstance(f, _ToolErrorLogScrubber) for f in fastmcp_logger.filters):
        fastmcp_logger.addFilter(_ToolErrorLogScrubber())


def create_orphanet_mcp() -> FastMCP:
    """Build a FastMCP instance with all orphanet-link tools, resources, middleware."""
    _install_tool_error_log_scrubber()
    mcp = FastMCP(
        name="orphanet-link",
        version=__version__,
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
