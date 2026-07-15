"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and ``_meta``
on success, and converts any exception into a structured error dict (returned,
never raised) so the LLM sees a typed failure rather than an opaque masked
message.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from pydantic import ValidationError as PydanticValidationError

from orphanet_link.constants import ERROR_CODES, ErrorCode
from orphanet_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    WithdrawnEntryError,
)
from orphanet_link.mcp import metrics
from orphanet_link.mcp.next_commands import cmd, default_error_next_commands, withdrawn_recovery
from orphanet_link.mcp.untrusted_content import (
    UntrustedTextLimitError,
    sanitize_message,
    sanitize_tree,
)
from orphanet_link.services.shaping import DEFAULT_RESPONSE_MODE

logger = logging.getLogger(__name__)

#: Fixed, path-free public message for a missing/unreadable local index. The
#: underlying DataUnavailableError may embed a host filesystem path or a raw sqlite
#: str(exc) (see data/repository.py), so its classified message is SEVERED to this
#: constant rather than surfaced -- code-point stripping alone would leave the path.
_DATA_UNAVAILABLE_MESSAGE = (
    "The local Orphanet index is unavailable. Run `orphanet-link-data build`."
)

# Per-call _meta is kept lean: static provenance (citation, Orphanet release)
# lives ONLY in get_server_capabilities. Per-call _meta carries a fixed
# research-use disclaimer (unsafe_for_clinical_use, present at every response_mode,
# success and error paths -- fleet disclaimer standardization) plus dynamic
# fields: tool, request_id, [next_commands, capabilities_version, elapsed_ms] --
# and those three are tiered by response_mode (see _shape_meta).
#
# Every code here is in the CLOSED enum of Response-Envelope Standard v1
# (constants.ERROR_CODES). See _classify for the three legacy codes this backend
# invented and where they now land.
_RETRYABLE = {"rate_limited", "upstream_unavailable"}

#: The closed enum as a set, for the runtime backstop in _classify (the ONE branch that
#: does not hardcode its code is McpToolError, which returns error_code verbatim).
_CLOSED_ERROR_CODES: frozenset[str] = frozenset(ERROR_CODES)


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool and recovery."""

    tool_name: str
    fallback: dict[str, Any] | None = field(default=None)
    arguments: dict[str, Any] = field(default_factory=dict)
    #: The caller's verbosity, used to tier _meta (see :func:`_shape_meta`).
    response_mode: str = DEFAULT_RESPONSE_MODE
    #: When False (default), the verbose body ``orphanet_version`` string is trimmed
    #: in the lean modes (minimal/compact) because ``_meta.data_version`` already
    #: grounds the call (P1.2). The discovery tools set this True -- the human-readable
    #: release string is THEIR product, not redundant per-call provenance.
    keep_version: bool = False


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message.

    ``error_code`` is typed ``ErrorCode`` (the closed Response-Envelope v1 enum), so a
    caller cannot pass a code of their own invention -- mypy rejects it at the call site.
    ``_classify`` additionally re-checks it against the enum at runtime and severs anything
    outside to ``internal``, because a type annotation is not enforced by the interpreter
    and this value is echoed verbatim onto an ``isError: true`` envelope's ``error_code``.
    """

    def __init__(self, *, error_code: ErrorCode, message: str) -> None:
        """Store an error code and client-safe message."""
        super().__init__(message)
        self.error_code: ErrorCode = error_code
        self.message = message


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


def _capabilities_version() -> str | None:
    """Cached discovery-contract hash for the ``_meta`` echo (never raises)."""
    try:
        from orphanet_link.mcp.capabilities import capabilities_version

        return capabilities_version()
    except Exception:  # pragma: no cover - the _meta echo must never break a tool
        return None


def _safe_message(exc: BaseException) -> str:
    # Code-point backstop for SERVER-AUTHORED classified messages (our own fixed
    # templates, possibly echoing a caller-supplied identifier). Attacker-
    # influenceable prose / local paths are severed to fixed messages at the source
    # and in _classify -- never routed through here.
    return sanitize_message(str(exc) or exc.__class__.__name__)


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, client_safe_message)`` for an exception.

    Every code returned here is in the CLOSED enum of Response-Envelope Standard v1:
    ``invalid_input · not_found · ambiguous_query · upstream_unavailable ·
    rate_limited · internal``. This function is the ONE place the mapping happens, so
    a code outside the enum cannot reach the wire.

    Three codes this backend used to invent, and where they now land:

    ``limit_exceeded`` -> ``invalid_input``
        The caller fixes it by narrowing the request (a smaller ``limit``/batch), which
        is what ``invalid_input`` means. ``recovery_action`` stays ``reformulate_input``
        and the ceiling detail still rides the message, so nothing actionable is lost.

    ``data_unavailable`` -> ``upstream_unavailable``
        The local Orphanet index is a data dependency; "it is not there" is the same
        situation the caller must handle as an upstream being down, and it stays
        retryable. ``next_commands`` still chains to ``get_diagnostics``.

    ``internal_error`` -> ``internal``
        The same meaning; the enum simply spells it ``internal``.
    """
    if isinstance(exc, McpToolError):
        # error_code is typed ErrorCode, but a type annotation is not enforced by the
        # interpreter, and this value is echoed VERBATIM onto the wire (it is the only
        # branch that does not hardcode its code). Re-check against the closed enum and
        # sever anything outside to `internal` so an off-contract code -- e.g. from a
        # miswritten raise, or a runtime that ignored the type -- can never be advertised.
        if exc.error_code in _CLOSED_ERROR_CODES:
            return exc.error_code, exc.message
        return "internal", exc.message
    if isinstance(exc, NotFoundError):  # WithdrawnEntryError subclasses this
        return "not_found", _safe_message(exc)
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", _safe_message(exc)
    if isinstance(exc, InvalidInputError):
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, UntrustedTextLimitError):
        # A fenced response exceeded a Response-Envelope v1.1 ceiling (object count /
        # per-object bytes / total bytes). The standard forbids silent omission, so the
        # ceiling detail is still surfaced -- as invalid_input, the closed-enum code for
        # "the request as posed cannot be served; reformulate it".
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, DataUnavailableError):
        # SEVER: the message may embed a host path / sqlite str(exc); never surface it.
        return "upstream_unavailable", _DATA_UNAVAILABLE_MESSAGE
    if isinstance(exc, RateLimitError):
        return "rate_limited", "Upstream rate limit hit. Retry shortly."
    if isinstance(exc, ServiceUnavailableError | DownloadError):
        return "upstream_unavailable", "The upstream is temporarily unavailable."
    if isinstance(exc, PydanticValidationError):
        # Map to a FIXED reason: the pydantic ``msg`` can echo the rejected input, and
        # the ``loc`` (argument name) is caller-controlled -- code-point-strip it and
        # never interpolate the pydantic message prose.
        first = exc.errors(include_url=False)[0]
        loc = sanitize_message(".".join(str(p) for p in first["loc"]) or "input")
        return "invalid_input", f"Invalid value for argument `{loc}`."
    return "internal", "An internal error occurred. The request was not completed."


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Public per-item classifier: ``(error_code, client-safe message)``.

    Batch tools catch typed exceptions per item and need the same taxonomy the
    error envelope applies, without building a whole envelope. Delegates to the
    shared classifier so single-item and batch error shaping never diverge.
    """
    return _classify(exc)


def _recovery_action(error_code: str) -> str:
    if error_code in _RETRYABLE:
        return "retry_backoff"
    # The client-fixable input errors: the caller changes the call and retries. (An
    # over-ceiling response is now invalid_input and routes here, as it always did.)
    if error_code in {"invalid_input", "not_found", "ambiguous_query"}:
        return "reformulate_input"
    return "switch_tool"


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        # Code-point backstop (e.g. a server-authored McpToolError.message). The whole
        # envelope is also recursively sanitized in run_mcp_tool before it is returned.
        "message": sanitize_message(message),
        "retryable": error_code in _RETRYABLE,
        "recovery_action": _recovery_action(error_code),
        "_meta": {
            "tool": context.tool_name,
            "request_id": _request_id(),
            "source": "orphanet",
            "unsafe_for_clinical_use": True,
        },
    }
    if isinstance(exc, InvalidInputError):
        if exc.field is not None:
            envelope["field"] = exc.field
        if exc.allowed is not None:
            envelope["allowed_values"] = exc.allowed
        if exc.hint is not None:
            envelope["hint"] = exc.hint
    if isinstance(exc, AmbiguousQueryError) and exc.candidates:
        envelope["candidates"] = exc.candidates
        envelope["_meta"]["next_commands"] = [
            cmd("get_disease", term=(c.get("orpha_code") or c.get("mondo_id")))
            for c in exc.candidates[:3]
            if c.get("orpha_code") or c.get("mondo_id")
        ] or [cmd("get_server_capabilities")]
        return envelope
    if isinstance(exc, WithdrawnEntryError):
        envelope["obsolete"] = True
        envelope["withdrawn_status"] = exc.withdrawn_status
        envelope["replaced_by"] = exc.replaced_by
        envelope["_meta"]["next_commands"] = withdrawn_recovery(exc.replaced_by)
        return envelope
    if isinstance(exc, NotFoundError) and exc.suggestions:
        envelope["candidates"] = exc.suggestions
        steps = [
            cmd("get_disease", term=(s.get("orpha_code") or s.get("mondo_id")))
            for s in exc.suggestions[:3]
            if s.get("orpha_code") or s.get("mondo_id")
        ]
        query = str(context.arguments.get("term", "") or context.arguments.get("query", ""))
        if query:
            steps.append(cmd("search_diseases", query=query))
        envelope["_meta"]["next_commands"] = steps or [cmd("get_server_capabilities")]
        return envelope
    if context.fallback is not None:
        envelope["_meta"]["next_commands"] = [context.fallback]
    else:
        envelope["_meta"]["next_commands"] = default_error_next_commands(
            context.tool_name, error_code, context.arguments
        )
    return envelope


def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
    constraints: tuple[list[str], str] | None = None,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    When ``constraints`` is supplied the failure is an invalid *value* on a known
    argument, so ``allowed_values`` carries the valid range/enum (not the list of
    argument *names*) and the message states the constraint.
    """
    # ``loc`` is a caller-controlled argument NAME (an unknown/unexpected keyword can
    # carry forbidden code points): code-point-strip it before it reaches ``field`` or
    # any interpolated message. ``human``/``signature`` are server-authored.
    loc = sanitize_message(loc)
    if constraints is not None:
        allowed, human = constraints
        message = f"Invalid value for argument `{loc}` of {tool_name}: {human}."
        return {
            "success": False,
            "error_code": "invalid_input",
            "message": sanitize_message(message),
            "retryable": False,
            "recovery_action": "reformulate_input",
            "field": loc,
            "allowed_values": allowed,
            "hint": signature,
            "_meta": {
                "tool": tool_name,
                "request_id": _request_id(),
                "source": "orphanet",
                "unsafe_for_clinical_use": True,
                "next_commands": [cmd("get_server_capabilities")],
            },
        }
    if error_type == "missing_argument":
        head = f"Missing required argument `{loc}` for {tool_name}."
    elif error_type == "unexpected_keyword_argument":
        head = f"Unknown argument `{loc}` for {tool_name}."
    else:
        head = f"Invalid value for argument `{loc}` of {tool_name}."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    return {
        "success": False,
        "error_code": "invalid_input",
        "message": sanitize_message(message),
        "retryable": False,
        "recovery_action": "reformulate_input",
        "field": loc,
        "allowed_values": valid_params,
        "hint": signature,
        "_meta": {
            "tool": tool_name,
            "request_id": _request_id(),
            "source": "orphanet",
            "unsafe_for_clinical_use": True,
            "next_commands": [cmd("get_server_capabilities")],
        },
    }


def _data_version() -> str | None:
    """Cached short fingerprint of the loaded Orphanet release (never raises)."""
    try:
        from orphanet_link.mcp.capabilities import data_version

        return data_version()
    except Exception:  # pragma: no cover - the _meta echo must never break a tool
        return None


def _stamp_capabilities_version(meta: dict[str, Any]) -> None:
    """Add the cached capabilities_version to a ``_meta`` block when available."""
    version = _capabilities_version()
    if version:
        meta["capabilities_version"] = version


def _stamp_data_version(meta: dict[str, Any]) -> None:
    """Add the cached data_version release anchor to a ``_meta`` block when available."""
    fingerprint = _data_version()
    if fingerprint:
        meta["data_version"] = fingerprint


def _trim_version(result: dict[str, Any], ctx: McpErrorContext) -> None:
    """Drop the verbose body ``orphanet_version`` string in the lean modes (P1.2).

    ``_meta.data_version`` (a short release-hash) already grounds every call, so the
    long human-readable release string is redundant per-call weight in
    minimal/compact and is shipped only in standard/full. The discovery tools opt out
    (``keep_version``) because that string is their primary payload.
    """
    if not ctx.keep_version and ctx.response_mode in ("minimal", "compact"):
        result.pop("orphanet_version", None)


def _shape_meta(meta: dict[str, Any], response_mode: str) -> dict[str, Any]:
    """Tier ``_meta`` verbosity by ``response_mode`` to control the per-call token tax.

    - ``minimal``: the trace essentials plus the data anchor --
      ``{tool, request_id, source, unsafe_for_clinical_use, data_version}``. The caller
      opted out of guidance, so ``next_commands`` / ``capabilities_version`` /
      ``elapsed_ms`` are dropped, but ``data_version`` stays so even the leanest answer
      is tied to its Orphanet release.
    - ``compact`` (default): keep ``next_commands`` (workflow guidance) and
      ``capabilities_version`` (the warm-client cache key the discovery contract leans
      on), but drop the ``elapsed_ms`` observability echo from the hot path -- it is
      still recorded server-side and surfaced by ``get_diagnostics``.
    - ``standard`` / ``full``: the complete ``_meta``, including ``elapsed_ms``.

    The universal ``next_commands`` invariant therefore holds for ``compact`` and
    richer (every default response still chains); ``minimal`` is the documented opt-out.
    ``unsafe_for_clinical_use`` is NOT tiered -- it is a fixed research-use disclaimer
    present at every ``response_mode``, on both the success and error envelopes (fleet
    disclaimer standardization; see the module docstring).
    """
    if response_mode == "minimal":
        lean = {
            "tool": meta["tool"],
            "request_id": meta["request_id"],
            "source": "orphanet",
            "unsafe_for_clinical_use": True,
        }
        if "data_version" in meta:
            lean["data_version"] = meta["data_version"]
        return lean
    if response_mode in ("standard", "full"):
        return meta
    return {k: v for k, v in meta.items() if k != "elapsed_ms"}


def error_result(envelope: dict[str, Any]) -> ToolResult:
    """Wrap an error envelope so it carries BOTH the structure and MCP's ``isError``.

    Response-Envelope Standard v1: *"isError: true is REQUIRED so clients surface the
    error to the model for self-correction."* A tool that RETURNS a dict can never set
    it (fastmcp/tools/base.py builds the ToolResult with ``is_error`` defaulted false),
    so every error envelope this server returned was delivered to the client as a
    SUCCESSFUL call carrying ``success: false`` -- a client branching on ``isError``,
    as the protocol tells it to, saw nothing wrong.

    Raising instead is NOT the fix: FastMCP's raise path sets ``isError`` but discards
    ``structuredContent`` entirely, which would throw away the machine-readable
    envelope (error_code, field, allowed_values, next_commands) the model needs to
    self-correct. Returning a ``ToolResult`` is the only shape that gives us both.

    The TextContent mirror is kept in step with ``structured_content`` so neither
    caller-visible surface disagrees with the other.
    """
    return ToolResult(
        structured_content=envelope,
        content=[TextContent(type="text", text=json.dumps(envelope))],
        is_error=True,
    )


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any] | ToolResult:
    """Execute a tool body.

    Returns the result dict on success, or -- on failure -- a ``ToolResult`` carrying
    the structured error envelope AND ``isError: true`` (never a bare dict, which
    cannot set the protocol flag; never a raise, which would discard the envelope).
    """
    ctx = context or McpErrorContext(tool_name=tool_name)
    start = time.perf_counter()
    try:
        result = await call()
        elapsed = int((time.perf_counter() - start) * 1000)
        if isinstance(result, dict):
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            success = bool(result.setdefault("success", True))
            meta = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
                "source": "orphanet",
                "unsafe_for_clinical_use": True,
                "elapsed_ms": elapsed,
            }
            _stamp_capabilities_version(meta)
            _stamp_data_version(meta)
            result["_meta"] = _shape_meta(meta, ctx.response_mode)
            _trim_version(result, ctx)
            metrics.record(tool_name, elapsed, ok=success, response_mode=ctx.response_mode)
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        elapsed = int((time.perf_counter() - start) * 1000)
        envelope = _error_envelope(exc, ctx)
        envelope["_meta"]["elapsed_ms"] = elapsed
        _stamp_capabilities_version(envelope["_meta"])
        _stamp_data_version(envelope["_meta"])
        request_id = envelope["_meta"].get("request_id")
        envelope["_meta"] = _shape_meta(envelope["_meta"], ctx.response_mode)
        metrics.record(tool_name, elapsed, ok=False, response_mode=ctx.response_mode)
        logger.warning(
            "mcp_tool_error tool=%s code=%s request_id=%s exc=%s",
            tool_name,
            envelope["error_code"],
            request_id,
            exc.__class__.__name__,
        )
        # Whole-envelope code-point backstop over EVERY string leaf (message, field,
        # allowed_values, hint, candidates, replaced_by, next_commands arguments, _meta)
        # so no forbidden code point survives on any error surface, whatever built it.
        return error_result(cast("dict[str, Any]", sanitize_tree(envelope)))
