"""Contract: every error envelope carries MCP's ``isError: true``.

Response-Envelope Standard v1: *"``isError: true`` is REQUIRED so clients surface the
error to the model for self-correction."*

orphanet-link returned its error envelopes as plain dicts. A returned dict CANNOT set
the protocol flag — FastMCP builds the ``ToolResult`` with ``is_error`` defaulted false
(``fastmcp/tools/base.py``) — so every error this server produced arrived at the client
as ``isError: false``: a **successful call** that merely happened to contain
``success: false`` in its body. A client branching on ``isError``, exactly as the MCP
spec tells it to, saw nothing wrong. The fleet behaviour gate found this on EVERY error
envelope on this server.

Raising is not the alternative: FastMCP's raise path sets ``isError`` but emits
``structuredContent: null``, discarding the machine-readable envelope (``error_code``,
``field``, ``allowed_values``, ``next_commands``) the model needs to self-correct.
``ToolResult(structured_content=envelope, is_error=True)`` is the only shape that
delivers both.

Both error paths are covered:

* the TOOL BODY path (``run_mcp_tool`` catches a typed exception), and
* the ARGUMENT-BINDING path (``ArgValidationMiddleware`` catches pydantic before the
  body ever runs) — which is the one that used to *downgrade* FastMCP's own correct
  ``isError: true`` into a plain result while reshaping it into a nicer envelope.

The tool list is derived from the registry, so a new tool is covered the day it ships.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from orphanet_link.exceptions import NotFoundError
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.facade import create_orphanet_mcp

#: A value that is a well-formed argument but names nothing in any corpus, so every
#: term-taking tool drives its own not_found/invalid_input path.
_NO_SUCH_TERM = "ORPHA:99999999"


def _registered_tool_names() -> list[str]:
    mcp = create_orphanet_mcp()
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


TOOL_NAMES = _registered_tool_names()


async def _tool(facade: FastMCP, name: str) -> Any:
    return next(t for t in await facade.list_tools() if t.name == name)


def _required(tool: Any) -> list[str]:
    return list(dict(getattr(tool, "parameters", None) or {}).get("required") or [])


async def test_tool_body_error_sets_is_error() -> None:
    """The run_mcp_tool boundary: a typed exception becomes an isError ToolResult."""

    async def call() -> dict[str, Any]:
        raise NotFoundError("nope")

    result = await run_mcp_tool(
        "get_disease", call, context=McpErrorContext(tool_name="get_disease")
    )
    assert isinstance(result, ToolResult), "an error must be a ToolResult, not a bare dict"
    assert result.is_error is True, "Response-Envelope v1: isError:true is REQUIRED"
    assert isinstance(result.structured_content, dict), (
        "the machine-readable envelope must survive — raising would have nulled it"
    )
    assert result.structured_content["success"] is False
    assert result.structured_content["error_code"] == "not_found"


async def test_success_does_not_set_is_error() -> None:
    """The flag must mean something: a successful call never raises it."""

    async def call() -> dict[str, Any]:
        return {"results": []}

    result = await run_mcp_tool("get_disease", call)
    assert not isinstance(result, ToolResult), "success returns the plain envelope dict"
    assert result["success"] is True


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_every_error_capable_tool_sets_is_error(facade: FastMCP, tool_name: str) -> None:
    """Drive each tool's error path through its own required args and demand isError."""
    tool = await _tool(facade, tool_name)
    required = _required(tool)
    if not required:
        pytest.skip(f"{tool_name} takes no required argument to make unusable")

    # A well-formed but nonexistent value for every required parameter. Array-typed
    # params take it as a single-item list, so the batch tools are covered too.
    schema = dict(getattr(tool, "parameters", None) or {})
    props = schema.get("properties") or {}
    args: dict[str, Any] = {}
    for name in required:
        prop = props.get(name) or {}
        types = {prop.get("type")} | {
            b.get("type") for b in prop.get("anyOf") or [] if isinstance(b, dict)
        }
        args[name] = [_NO_SUCH_TERM] if "array" in types else _NO_SUCH_TERM

    result = await tool.fn(**args)
    if not isinstance(result, ToolResult):
        # A partial-success batch legitimately succeeds with per-item failures inside.
        assert result.get("success") is True
        pytest.skip(f"{tool_name} reports per-item failure inside a successful envelope")

    assert result.is_error is True, (
        f"{tool_name}: returned an error envelope "
        f"(success={result.structured_content.get('success')!r}, "
        f"error_code={result.structured_content.get('error_code')!r}) with isError=False. "
        "A client branching on isError reads this as a SUCCESSFUL call."
    )
    assert result.structured_content["success"] is False
