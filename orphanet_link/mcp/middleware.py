"""FastMCP middleware that wraps argument-binding failures in the error envelope.

FastMCP validates call arguments with pydantic inside ``FunctionTool.run()`` --
before the registered tool body executes -- so a wrong argument *name*/*type* or a
*missing required* argument raises a ``pydantic.ValidationError`` that never reaches
``run_mcp_tool``'s error boundary. This middleware catches it at ``on_call_tool``
and returns the standard ``invalid_input`` envelope (valid names + a did-you-mean).
It also normalizes curated argument aliases (e.g. ``term`` -> ``query``) before
dispatch and discloses any rewrite under ``_meta.argument_aliases_applied``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolRequestParams
from pydantic import ValidationError as PydanticValidationError

from orphanet_link.mcp.arg_help import (
    describe_constraints,
    describe_type_expectation,
    did_you_mean,
    normalize_alias_args,
    tool_signature,
)
from orphanet_link.mcp.envelope import build_arg_error_envelope, error_result
from orphanet_link.mcp.untrusted_content import sanitize_tree

logger = logging.getLogger(__name__)


class ArgValidationMiddleware(Middleware):
    """Reshape argument-binding errors into the envelope and apply argument aliases."""

    def __init__(self) -> None:
        """Initialise the per-tool parameter-schema cache."""
        self._schema_cache: dict[str, dict[str, Any]] = {}

    async def _schema(self, context: MiddlewareContext[Any], name: str) -> dict[str, Any]:
        if name not in self._schema_cache:
            fctx = context.fastmcp_context
            if fctx is None:
                raise RuntimeError("no fastmcp context")
            tool = await fctx.fastmcp.get_tool(name)
            self._schema_cache[name] = dict(getattr(tool, "parameters", None) or {})
        return self._schema_cache[name]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Normalize aliases, then convert binding errors into the envelope."""
        name = context.message.name
        try:
            schema = await self._schema(context, name)
        except Exception:  # registry miss: let core handle the call untouched
            return await call_next(context)

        valid = list(schema.get("properties", {}).keys())
        new_args, applied = normalize_alias_args(valid, context.message.arguments or {})
        context.message.arguments = new_args

        try:
            result = await call_next(context)
        except FastMCPValidationError as exc:
            cause = exc.__cause__
            if not isinstance(cause, PydanticValidationError):
                raise
            return self._error_result(name, valid, schema, cause)
        except PydanticValidationError as exc:
            return self._error_result(name, valid, schema, exc)

        if (
            applied
            and isinstance(result, ToolResult)
            and isinstance(result.structured_content, dict)
        ):
            meta = result.structured_content.setdefault("_meta", {})
            meta["argument_aliases_applied"] = [list(pair) for pair in applied]
        return result

    def _error_result(
        self,
        name: str,
        valid: list[str],
        schema: dict[str, Any],
        exc: PydanticValidationError,
    ) -> ToolResult:
        first = exc.errors(include_url=False)[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "input"
        error_type = str(first.get("type", "value_error"))
        # The failing param may be a top-level name (``prefixes``) OR an item of an
        # array param (``prefixes.0`` for a bad element of a list[Literal] vocabulary).
        # Resolve to the base parameter so a bad ARRAY ITEM surfaces its item enum,
        # instead of being misread as an unknown argument named "prefixes.0".
        base = loc.split(".", 1)[0]
        # A real param with a bad *value* -> surface the constraint (enum/range)
        # or, failing that, the expected type + an example -- never the list of
        # argument names (which is reserved for genuinely unknown arguments).
        constraints = None
        target = loc if loc in valid else (base if base in valid else None)
        if target is not None and error_type not in ("missing", "missing_argument"):
            field_schema = schema.get("properties", {}).get(target, {})
            constraints = describe_constraints(field_schema) or describe_type_expectation(
                field_schema
            )
        # Only offer a name suggestion when the argument itself is unknown -- not when a
        # valid array param merely got a bad item (base in valid).
        suggestion = did_you_mean(loc, valid) if loc not in valid and base not in valid else None
        envelope = build_arg_error_envelope(
            tool_name=name,
            loc=loc,
            error_type=error_type,
            valid_params=valid,
            signature=tool_signature(name, schema),
            suggestion=suggestion,
            constraints=constraints,
        )
        # Whole-envelope code-point backstop (this frame bypasses run_mcp_tool).
        envelope = sanitize_tree(envelope)
        # Log ONLY stable, low-cardinality metadata (tool name + the pydantic error
        # type). The offending argument NAME is caller-controlled, so it is never
        # written to the log sink -- the sanitized value still rides the envelope.field.
        logger.warning("mcp_arg_error tool=%s type=%s", name, error_type)
        # is_error=True: an argument-binding failure IS an error, and a client that
        # branches on MCP's isError must see one. FastMCP's own default for a failed
        # pydantic validation is already isError=true -- this middleware was CATCHING
        # that and handing back a plain (isError-false) result, so reshaping the
        # failure into a useful envelope was silently downgrading it to a success.
        return error_result(envelope)
