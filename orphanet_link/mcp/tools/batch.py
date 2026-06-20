"""Batch tools: resolve_disease_batch, get_disease_batch (partial success).

These loop the existing single-item service calls behind one tool round-trip. Each
item resolves independently: a per-item failure becomes an ``{ok: false, error_code,
message}`` row (classified by the shared :func:`classify_exception`) rather than
failing the whole call. A batch-size cap returns a single ``invalid_input`` error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from orphanet_link.constants import MAX_BATCH_ITEMS
from orphanet_link.exceptions import InvalidInputError
from orphanet_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from orphanet_link.mcp.envelope import McpErrorContext, classify_exception, run_mcp_tool
from orphanet_link.mcp.next_commands import after_get_disease_batch, after_resolve_batch
from orphanet_link.mcp.schemas import BATCH_DISEASE_SCHEMA, BATCH_RESOLVE_SCHEMA
from orphanet_link.mcp.service_adapters import get_orphanet_service
from orphanet_link.mcp.tools._common import FieldsArg, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

#: Hard cap on items per batch call (bounds token blowup / abuse). Defined in
#: ``constants`` so capabilities.limits advertises the exact value enforced here.
MAX_BATCH = MAX_BATCH_ITEMS

#: Max recovery candidates carried on an ambiguous batch item, tiered by verbosity
#: so a wide minimal batch does not balloon (P2.1 respects response_mode).
_CANDIDATE_CAP = {"minimal": 1, "compact": 3, "standard": 5, "full": 5}


def _require_batch(items: list[str], field: str) -> None:
    """Validate batch size: non-empty and within ``MAX_BATCH`` (logs an over-cap reject)."""
    if not items:
        raise InvalidInputError(f"{field} must be a non-empty list.", field=field)
    if len(items) > MAX_BATCH:
        # Reject (never silently truncate) and log the cap so over-fetch is observable.
        logger.warning(
            "batch size cap exceeded: %s got %d (max %d); rejecting", field, len(items), MAX_BATCH
        )
        raise InvalidInputError(
            f"{field} accepts at most {MAX_BATCH} items (got {len(items)}).", field=field
        )


def _error_row(
    exc: Exception, key: str, value: str, index: int, response_mode: str
) -> dict[str, Any]:
    """Build a per-item failure row, carrying recoverable candidates when available.

    An ``ambiguous_query`` (or a suggestion-bearing ``not_found``) item is now as
    self-recoverable as the single-call equivalent: the candidates ride along so the
    agent picks one without a second round trip (F-01). Count is tiered by mode.
    """
    code, message = classify_exception(exc)
    row: dict[str, Any] = {
        key: value,
        "index": index,
        "ok": False,
        "error_code": code,
        "message": message,
    }
    candidates = getattr(exc, "candidates", None) or getattr(exc, "suggestions", None)
    if candidates:
        row["candidates"] = candidates[: _CANDIDATE_CAP.get(response_mode, 3)]
    return row


def register_batch_tools(mcp: FastMCP) -> None:
    """Register the batch resolve/get tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_disease_batch",
        title="Resolve Diseases (batch)",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=BATCH_RESOLVE_SCHEMA,
        tags={"disease", "resolve", "batch"},
        description=(
            "Resolve many labels/ORPHAcodes/xrefs in one call (partial success: each "
            "item returns its resolution {orpha_code, name, match_type} or its own "
            "ok=false/error_code/message; the call never fails wholesale). "
            f"Max {MAX_BATCH} items; compact per item. "
            "Signature: resolve_disease_batch(queries, response_mode=)."
        ),
    )
    async def resolve_disease_batch(
        queries: Annotated[list[str], Field(description=f"1..{MAX_BATCH} labels/ids/xrefs.")],
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            _require_batch(queries, "queries")
            svc = get_orphanet_service()
            results: list[dict[str, Any]] = []
            version: str | None = None
            for index, query in enumerate(queries):
                try:
                    rec = svc.resolve_disease(query, response_mode=response_mode)
                    version = rec.pop("orphanet_version", None) or version  # grounded once
                    results.append({**rec, "query": query, "index": index, "ok": True})
                except Exception as exc:  # per-item boundary; the call still succeeds
                    results.append(_error_row(exc, "query", query, index, response_mode))
            payload: dict[str, Any] = {"count": len(results), "results": results}
            if version:
                payload["orphanet_version"] = version
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_batch(payload)
            return payload

        return await run_mcp_tool(
            "resolve_disease_batch",
            call,
            context=McpErrorContext("resolve_disease_batch", response_mode=response_mode),
        )

    @mcp.tool(
        name="get_disease_batch",
        title="Get Diseases (batch)",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=BATCH_DISEASE_SCHEMA,
        tags={"disease", "batch"},
        description=(
            "Fetch many disease records in one call (partial success per item: each "
            "row is the record or its own ok=false/error_code/message). Each term "
            "accepts an ORPHAcode, label, or xref CURIE; pass fields=[...] for a sparse "
            f"projection. Max {MAX_BATCH} items; compact per item. "
            "Signature: get_disease_batch(terms, response_mode=, fields=)."
        ),
    )
    async def get_disease_batch(
        terms: Annotated[list[str], Field(description=f"1..{MAX_BATCH} ids/labels/xrefs.")],
        response_mode: ResponseMode = "compact",
        fields: FieldsArg = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            _require_batch(terms, "terms")
            svc = get_orphanet_service()
            results: list[dict[str, Any]] = []
            version: str | None = None
            for index, term in enumerate(terms):
                try:
                    rec = svc.get_disease(term, response_mode=response_mode, fields=fields)
                    version = rec.pop("orphanet_version", None) or version  # grounded once
                    results.append({**rec, "term": term, "index": index, "ok": True})
                except Exception as exc:  # per-item boundary; the call still succeeds
                    results.append(_error_row(exc, "term", term, index, response_mode))
            payload: dict[str, Any] = {"count": len(results), "results": results}
            if version:
                payload["orphanet_version"] = version
            payload.setdefault("_meta", {})["next_commands"] = after_get_disease_batch(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_batch",
            call,
            context=McpErrorContext("get_disease_batch", response_mode=response_mode),
        )
