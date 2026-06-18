"""Classification/hierarchy tools: classification, ancestors, descendants."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from orphanet_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.next_commands import after_ancestors, after_descendants, after_parents
from orphanet_link.mcp.schemas import (
    ANCESTORS_SCHEMA,
    DESCENDANTS_SCHEMA,
    DISEASE_CLASSIFICATION_SCHEMA,
)
from orphanet_link.mcp.service_adapters import get_orphanet_service
from orphanet_link.mcp.tools._common import ResponseMode, TermStr

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ClosureLimit = Annotated[int, Field(ge=1, le=1000, description="Max rows returned (default 200).")]
_ClosureOffset = Annotated[
    int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
]


def register_classification_tools(mcp: FastMCP) -> None:
    """Register the classification and hierarchy tools on a FastMCP instance."""

    @mcp.tool(
        name="get_disease_classification",
        title="Get Disease Classification",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_CLASSIFICATION_SCHEMA,
        tags={"disease", "hierarchy", "classification"},
        description=(
            "Return the immediate Orphanet classification parents and children for a "
            "disorder. Use get_disease_ancestors / get_disease_descendants for the "
            "transitive closure. "
            "Signature: get_disease_classification(term, response_mode=)."
        ),
    )
    async def get_disease_classification(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_classification(
                term, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_parents(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_classification",
            call,
            context=McpErrorContext(
                "get_disease_classification", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_ancestors",
        title="Get Disease Ancestors",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANCESTORS_SCHEMA,
        tags={"disease", "hierarchy", "closure"},
        description=(
            "Return all transitive ancestors (broader diseases) of an Orphanet disorder "
            "via the precomputed closure, with a pagination block {total, returned, "
            "limit, offset, truncated, next_offset}. When truncated, next_commands "
            "carries a forward-page step. Use get_disease_classification for only the "
            "immediate parents. "
            "Signature: get_disease_ancestors(term, limit=, offset=, response_mode=)."
        ),
    )
    async def get_disease_ancestors(
        term: TermStr,
        limit: _ClosureLimit = 200,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_ancestors(
                term, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_ancestors(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_ancestors",
            call,
            context=McpErrorContext(
                "get_disease_ancestors", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_descendants",
        title="Get Disease Descendants",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DESCENDANTS_SCHEMA,
        tags={"disease", "hierarchy", "closure"},
        description=(
            "Return all transitive descendants (more specific diseases) of an Orphanet "
            "disorder via the precomputed closure, with a pagination block {total, "
            "returned, limit, offset, truncated, next_offset}. When truncated, "
            "next_commands carries a forward-page step. Use get_disease_classification "
            "for only the immediate children. "
            "Signature: get_disease_descendants(term, limit=, offset=, response_mode=)."
        ),
    )
    async def get_disease_descendants(
        term: TermStr,
        limit: _ClosureLimit = 200,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_descendants(
                term, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_descendants(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_descendants",
            call,
            context=McpErrorContext(
                "get_disease_descendants", arguments={"term": term}, response_mode=response_mode
            ),
        )
