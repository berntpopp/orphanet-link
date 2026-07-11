"""MCP facade for orphanet-link: assemble the FastMCP instance with all tools."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from orphanet_link import __version__
from orphanet_link.mcp.capabilities import register_capability_resources
from orphanet_link.mcp.middleware import ArgValidationMiddleware
from orphanet_link.mcp.notfound_guard import (
    NotFoundGuard,
    install_protocol_error_handler,
    install_validation_log_filter,
)
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
    # Layer 5: scrub FastMCP-core / MCP-SDK validation + handler logs that would
    # echo the caller-supplied tool name / resource URI / prompt name (with any
    # control/zero-width/bidi/NUL code points) at ANY level. Attach now, after
    # FastMCP's own non-propagating Rich handlers exist. See notfound_guard.py.
    install_validation_log_filter()

    # Layer 1 (tool-name preflight) + Layer 2 (on_read_resource boundary). Added
    # FIRST so NotFoundGuard is the OUTERMOST middleware: an unknown tool name is
    # answered with a fixed, name-free envelope before core dispatch can reflect
    # it, and a failed/unknown resource read never echoes the requested URI.
    mcp.add_middleware(NotFoundGuard())

    register_discovery_tools(mcp)
    register_disease_tools(mcp)
    register_association_tools(mcp)
    register_classification_tools(mcp)
    register_xref_tools(mcp)
    register_batch_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    # Layer 3: install the protocol-handler backstop AFTER every tool/resource/
    # prompt is registered (so the request handlers exist). Outermost wrapper on
    # the raw CallTool/ReadResource/GetPrompt handlers -- catches the unknown-tool
    # *return* path and any resource/prompt dispatch error that would echo the
    # requested name/URI (the only layer covering the unknown-prompt surface).
    install_protocol_error_handler(mcp)

    return mcp
