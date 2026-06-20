"""Disease lookup tools: resolve_disease, search_diseases, get_disease."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from orphanet_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.next_commands import after_get_disease, after_resolve_disease, after_search
from orphanet_link.mcp.schemas import DISEASE_SCHEMA, RESOLVE_DISEASE_SCHEMA, SEARCH_SCHEMA
from orphanet_link.mcp.service_adapters import get_orphanet_service
from orphanet_link.mcp.tools._common import (
    FieldsArg,
    IncludeArg,
    QueryStr,
    ResponseMode,
    TermStr,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_disease_tools(mcp: FastMCP) -> None:
    """Register the disease lookup/search tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_disease",
        title="Resolve Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=RESOLVE_DISEASE_SCHEMA,
        tags={"disease", "resolve"},
        description=(
            "Resolve a disease label, synonym, or ORPHAcode (ORPHA:166024 or 166024) "
            "to the canonical Orphanet term {orpha_code, name, match_type}. An "
            "ambiguous label returns ambiguous_query with candidates. "
            "Signature: resolve_disease(query, response_mode=)."
        ),
    )
    async def resolve_disease(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().resolve_disease(query, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_disease(payload)
            return payload

        return await run_mcp_tool(
            "resolve_disease",
            call,
            context=McpErrorContext(
                "resolve_disease", arguments={"query": query}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="search_diseases",
        title="Search Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=SEARCH_SCHEMA,
        tags={"disease", "search"},
        description=(
            "Full-text search over Orphanet disease names, synonyms, and definitions "
            "(FTS, relevance-ranked). Returns {orpha_code, name, score} plus a "
            "pagination block {total, returned, limit, offset, truncated, next_offset}. "
            "When truncated, next_commands carries a forward-page step. Obsolete terms "
            "are excluded unless include_obsolete=true. "
            "Signature: search_diseases(query, limit=, offset=, include_obsolete=, response_mode=)."
        ),
    )
    async def search_diseases(
        query: QueryStr,
        limit: Annotated[int, Field(ge=1, le=200, description="Max hits (default 25).")] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        include_obsolete: Annotated[
            bool, Field(description="Include obsolete terms (default false).")
        ] = False,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().search_diseases(
                query,
                limit=limit,
                offset=offset,
                include_obsolete=include_obsolete,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = after_search(query, payload)
            return payload

        return await run_mcp_tool(
            "search_diseases",
            call,
            context=McpErrorContext(
                "search_diseases", arguments={"query": query}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease",
        title="Get Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_SCHEMA,
        tags={"disease"},
        description=(
            "Return an Orphanet disease record: definition, synonyms, grouped "
            "cross-references, classification parents/children, age of onset, "
            "inheritance, and disorder type. The term accepts an ORPHAcode, a "
            "label/synonym, or an external xref CURIE (resolved first). xrefs are "
            "grouped by source; any nested count is leaf rows, not groups. "
            "Pass fields=['xrefs.OMIM', ...] for a sparse projection, or "
            "include=['genes','phenotypes','prevalence','disability'] to compose a "
            "full entity in ONE call. "
            "Signature: get_disease(term, response_mode=, fields=, include=)."
        ),
    )
    async def get_disease(
        term: TermStr,
        response_mode: ResponseMode = "compact",
        fields: FieldsArg = None,
        include: IncludeArg = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease(
                term, response_mode=response_mode, fields=fields, include=include
            )
            payload.setdefault("_meta", {})["next_commands"] = after_get_disease(payload)
            return payload

        return await run_mcp_tool(
            "get_disease",
            call,
            context=McpErrorContext(
                "get_disease", arguments={"term": term}, response_mode=response_mode
            ),
        )
