"""FastMCP-core not-found reflection guard (Response-Envelope v1.1 fast-follow).

FastMCP core (pinned ``>=3.4.4,<4.0.0``) reflects the caller's OWN requested tool
name / resource URI / prompt name back to the caller (and to logs) BEFORE any
backend middleware runs. This module closes that residual with fixed, input-free
messages built from CONSTANTS only, mirroring the ratified fleet references
(``mondo``/``hpo`` registry preflight, ``clinvar`` protocol backstop,
``panelapp`` validation-log scrub filter; canonical ``autopvs1``/``hpo``
``feat/fastmcp-notfound-guard`` branches).

The reflected text is *caller-supplied* (a caller self-reflection surface), so
this is materially lower-risk than the upstream-injection leak the prior sweep
closed. It is still worth closing: the reflected name/URI -- with any
control/zero-width/bidi/NUL code points -- lands in shared operator logs and in
an agent's tool-result context. Fixed constants remove the channel entirely.

Layers (spec §3), copied per repo (no shared runtime library exists fleet-wide):

* Layer 1 -- ``on_call_tool`` registry preflight: ``get_tool(name)`` returns
  ``None`` for an unknown/disabled tool, so we return a fixed, name-free
  ``not_found`` envelope BEFORE core dispatch. Closes the unknown-TOOL surface;
  never echoes ``_meta.tool``.
* Layer 2 -- ``on_read_resource`` boundary: an unknown (URL-valid) resource makes
  core raise ``NotFoundError("Unknown resource: '<uri>'")``; we re-raise a fixed
  URI-free ``ResourceError``. orphanet-link registers only static string
  resources (no author-raised ``ResourceError``), so every read failure is masked.
* Layer 3 -- protocol-handler backstop: wraps the raw ``CallTool`` / ``ReadResource``
  / ``GetPrompt`` request handlers as the OUTERMOST layer. Replaces any non-envelope
  ``isError`` tool result (the unknown-tool *return* path) and re-raises fixed
  input-free messages for resource/prompt dispatch failures -- the ONLY layer that
  covers the unknown-PROMPT surface.
* Layer 5 -- validation-log scrub filter: FastMCP's pre-middleware and the MCP SDK
  session's request-validation logs echo the raw name/URI (with code points) on
  their own loggers/handlers. The filter neutralizes those records at the source
  logger so caller input never reaches a log sink at ANY level.

Layer 4 (arg-validation) is the existing :class:`ArgValidationMiddleware`
(``middleware.py``). Layer 6 (OTel span redaction) is a no-op here: FastMCP pulls
in ``opentelemetry-api`` transitively, but ``opentelemetry-sdk`` is absent, so the
tracer provider is non-recording (``ProxyTracerProvider``; spans never record) --
no span exception attributes are ever captured, so there is nothing to redact
(fleet policy: do NOT add the SDK dependency).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    GetPromptRequest,
    ReadResourceRequest,
    ServerResult,
    TextContent,
)

from orphanet_link.mcp.next_commands import cmd
from orphanet_link.mcp.untrusted_content import sanitize_tree

logger = logging.getLogger(__name__)

# Fixed, input-free public messages. They NEVER contain the requested name/URI
# (nor a ``_meta.tool`` echo of it): sanitation strips code points but not
# injection prose, so a fixed constant is the only safe source (prior-sweep
# lesson). ``not_found`` reuses this repo's error-code vocabulary.
_UNKNOWN_TOOL_MESSAGE = "The requested tool is not available."
_UNKNOWN_RESOURCE_MESSAGE = "The requested resource is not available."
_UNKNOWN_PROMPT_MESSAGE = "The requested prompt is not available."


def _request_id() -> str:
    """Short per-response id, matching :mod:`orphanet_link.mcp.envelope`."""
    return uuid.uuid4().hex[:12]


def unknown_tool_envelope() -> dict[str, Any]:
    """Return a fixed, name-free ``not_found`` error dict for an unknown tool.

    Reuses orphanet-link's error-envelope shape and ``not_found`` error code.
    ``_meta`` deliberately omits the ``tool`` key so the requested (caller-
    controlled) name is never reflected back on the wire. A defensive
    :func:`sanitize_tree` pass is the whole-envelope code-point backstop.
    """
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": "not_found",
        "message": _UNKNOWN_TOOL_MESSAGE,
        "retryable": False,
        "recovery_action": "reformulate_input",
        "_meta": {
            # NO "tool" key: never echo the caller-supplied requested name.
            "request_id": _request_id(),
            "source": "orphanet",
            "unsafe_for_clinical_use": True,
            "next_commands": [cmd("get_server_capabilities")],
        },
    }
    return cast("dict[str, Any]", sanitize_tree(envelope))


def unknown_tool_result() -> ToolResult:
    """A ``ToolResult`` carrying the fixed unknown-tool envelope + JSON mirror.

    Carries BOTH ``structured_content`` and a matching ``TextContent`` mirror so
    neither caller-visible surface echoes the requested name. ``is_error=True``
    flips ``CallToolResult.isError`` on the wire (RATIFIED fleet contract): with
    ``is_error=False`` the FastMCP Client would validate the structured result
    against a (non-existent) tool output schema, FAIL, and log the hostile
    requested name via its ``client`` logger.
    """
    envelope = unknown_tool_envelope()
    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(envelope))],
        structured_content=envelope,
        is_error=True,
    )


class NotFoundGuard(Middleware):
    """Layer 1 (tool preflight) + Layer 2 (resource boundary)."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        """Preflight the tool NAME; an unknown name never reaches core dispatch.

        ``get_tool`` returns ``None`` (it does not raise) for an unknown or
        disabled tool, so an unknown name is caught here and answered with a
        fixed, name-free envelope. Otherwise defer to the chain (arg-validation
        middleware + the tool body).
        """
        fctx = getattr(context, "fastmcp_context", None)
        name = getattr(getattr(context, "message", None), "name", None)
        if fctx is not None and isinstance(name, str):
            try:
                tool = await fctx.fastmcp.get_tool(name)
            except Exception:
                tool = object()  # resolution failure: defer to core, do not mask
            if tool is None:
                logger.warning("mcp_unknown_tool")
                return unknown_tool_result()
        return await call_next(context)

    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Emit a FIXED, URI-free error for a resource not-found / read failure.

        The requested URI is caller-controlled; FastMCP core echoes it
        (``Unknown resource: '<uri>'`` / ``Error reading resource '<uri>'``) in
        both the direct exception and the protocol error. orphanet-link's
        resources are static strings that never raise an author-authored
        ``ResourceError``, so every read failure is masked with a fixed message
        -- ``str(exc)`` (which preserves injection prose) is never re-published.
        """
        try:
            return await call_next(context)
        except Exception as exc:
            logger.warning("mcp_resource_error type=%s", type(exc).__name__)
            raise ResourceError(_UNKNOWN_RESOURCE_MESSAGE) from None


# ---------------------------------------------------------------------------
# Layer 3 -- protocol-handler backstop (clinvar pattern)
# ---------------------------------------------------------------------------
# FastMCP's CORE dispatch reflects the caller-controlled component name/URI
# verbatim when it is unknown -- notably ``Unknown prompt: '<name>'`` (raised by
# the low-level prompts/get handler, which mcp turns into an ``ErrorData`` echoing
# the name to the caller BEFORE any FastMCP middleware can intervene), and the
# unknown-tool RETURN path (an ``isError`` ``CallToolResult`` whose plain text
# echoes the name). This wraps the raw ``_mcp_server.request_handlers`` as the
# OUTERMOST layer so no requested name/URI (nor its code points) reaches the
# JSON-RPC error frame. All messages are fixed server-authored constants.


class _ProtocolError(Exception):
    """A dispatch-level failure re-raised with a FIXED, input-free message."""


def _is_structured_envelope(result: CallToolResult) -> bool:
    """True if an ``isError`` result carries one of OUR JSON envelopes.

    Distinguishes a structured orphanet-link error (already name-free -- it has an
    ``error_code``) from a RAW FastMCP dispatch error whose plain-text message
    echoes the caller-supplied tool name (``Unknown tool: '<name>'``).
    """
    if not result.content:
        return False
    text = getattr(result.content[0], "text", None)
    if not isinstance(text, str):
        return False
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return False
    return isinstance(obj, dict) and "error_code" in obj


def _fixed_tool_not_found_result() -> ServerResult:
    """A fixed, name-free ``CallToolResult`` for an unknown/failed tool dispatch."""
    envelope = unknown_tool_envelope()
    return ServerResult(
        CallToolResult(
            content=[TextContent(type="text", text=json.dumps(envelope))],
            structuredContent=envelope,
            isError=True,
        )
    )


def install_protocol_error_handler(mcp: FastMCP) -> None:
    """Wrap the tool/resource/prompt request handlers as the OUTERMOST layer.

    A FastMCP core not-found (or read) error can no longer reflect the
    caller-supplied name/URI. Install AFTER all tools/resources/prompts are
    registered so the handlers exist.
    """
    handlers = mcp._mcp_server.request_handlers

    call_tool = handlers.get(CallToolRequest)
    if call_tool is not None:

        async def wrapped_call_tool(
            request: CallToolRequest,
            *,
            _orig: Any = call_tool,
        ) -> ServerResult:
            try:
                result = cast(ServerResult, await _orig(request))
            except Exception:
                # A registered tool never raises here (run_mcp_tool returns an
                # envelope); any exception is a dispatch-level failure whose
                # message would echo the caller name -- mask it.
                logger.warning("mcp_protocol_error kind=tool")
                return _fixed_tool_not_found_result()
            # FastMCP *returns* an isError CallToolResult with a raw plain-text
            # message ("Unknown tool: '<name>'") for an unknown tool; replace any
            # isError result that is NOT one of our structured envelopes.
            root = getattr(result, "root", None)
            if (
                isinstance(root, CallToolResult)
                and root.isError
                and not _is_structured_envelope(root)
            ):
                logger.warning("mcp_protocol_error kind=tool")
                return _fixed_tool_not_found_result()
            return result

        handlers[CallToolRequest] = wrapped_call_tool

    for request_type, message, kind in (
        (ReadResourceRequest, _UNKNOWN_RESOURCE_MESSAGE, "resource"),
        (GetPromptRequest, _UNKNOWN_PROMPT_MESSAGE, "prompt"),
    ):
        orig = handlers.get(request_type)
        if orig is None:
            continue

        async def wrapped(
            request: Any,
            *,
            _orig: Any = orig,
            _message: str = message,
            _kind: str = kind,
        ) -> Any:
            try:
                return await _orig(request)
            except Exception as exc:
                # Re-raise with a FIXED, input-free message so no requested
                # name/URI (or its code points) reaches the JSON-RPC error frame.
                # Log the exception CLASS only (never the caller value).
                logger.warning("mcp_protocol_error kind=%s type=%s", _kind, type(exc).__name__)
                raise _ProtocolError(_message) from None

        handlers[request_type] = wrapped


# ---------------------------------------------------------------------------
# Layer 5 -- validation-log scrub filter (panelapp pattern)
# ---------------------------------------------------------------------------
#
# Each entry is a substring that appears in the ``record.msg`` of a FastMCP-core
# or MCP-SDK log line that reflects the caller-supplied name/URI (either
# interpolated into an f-string ``msg`` or carried in ``record.args``). Matching
# on ``msg`` covers both forms, because the scrub clears the args as well.
_SCRUB_MARKERS: tuple[str, ...] = (
    "Handler called: call_tool",
    "Handler called: read_resource",
    "Handler called: get_prompt",
    "Invalid arguments for tool",
    "Error calling tool",
    "Error reading resource",
    "Failed to validate request",
    "Failed to validate notification",
    "Message that failed validation",
    "Tool cache miss for",
)

# The source loggers on which those records are CREATED. A logging filter must be
# attached to the originating logger (or its handlers) -- logger-level filters are
# skipped during propagation, but they MUTATE the record in place at the source,
# so a downstream handler (even one on root) sees the already-scrubbed record.
# ``mcp.shared.session`` logs its request-validation failure via the module-level
# ``logging.warning`` / ``logging.debug`` (emitted on ROOT, name="root"), so root
# ("") covers it. ``fastmcp`` is FastMCP's non-propagating parent logger
# (propagate=False, its own Rich handlers): attaching there -- and to its handlers
# -- scrubs at the handler level any record propagating up to the Rich handlers.
_SCRUB_LOGGERS: tuple[str, ...] = (
    "",  # root -- mcp.shared.session request-validation failures
    "fastmcp",  # non-propagating parent + its Rich handlers (handler-level scrub)
    "fastmcp.server.server",
    "fastmcp.server.mixins.mcp_operations",
    "mcp.server.lowlevel.server",
    "mcp.shared.session",
)

_SCRUBBED_MESSAGE = "MCP request rejected (details omitted)."


class _ValidationLogScrubFilter(logging.Filter):
    """Scrub log records that would echo a caller-supplied tool name / URI.

    Replaces the record payload with fixed metadata (clearing ``args`` /
    ``exc_info`` / ``exc_text`` / ``stack_info``) so the caller-chosen name/URI --
    and any control/zero-width/bidi/NUL code points it carries -- can never reach
    a log or telemetry sink at ANY level. Always returns ``True``: the (now
    input-free) record is still emitted for operational visibility.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg if isinstance(record.msg, str) else ""
        if any(marker in msg for marker in _SCRUB_MARKERS):
            record.msg = _SCRUBBED_MESSAGE
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def install_validation_log_filter() -> None:
    """Idempotently attach the scrub filter to each source logger (and handlers).

    Call AFTER the FastMCP facade is built, so the framework's non-propagating
    Rich handlers already exist and receive the filter too.
    """
    for name in _SCRUB_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, _ValidationLogScrubFilter) for f in target.filters):
            target.addFilter(_ValidationLogScrubFilter())
        for handler in target.handlers:
            if not any(isinstance(f, _ValidationLogScrubFilter) for f in handler.filters):
                handler.addFilter(_ValidationLogScrubFilter())
