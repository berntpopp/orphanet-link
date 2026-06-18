"""Association tools: genes, phenotypes, prevalence, natural history, disability, find-by."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from orphanet_link.constants import HPO_FREQUENCIES
from orphanet_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.next_commands import (
    after_find_by,
    after_genes,
    after_phenotypes,
    after_simple_association,
)
from orphanet_link.mcp.schemas import (
    DISEASE_DISABILITY_SCHEMA,
    DISEASE_GENES_SCHEMA,
    DISEASE_NATURAL_HISTORY_SCHEMA,
    DISEASE_PHENOTYPES_SCHEMA,
    DISEASE_PREVALENCE_SCHEMA,
    FIND_BY_GENE_SCHEMA,
    FIND_BY_PHENOTYPE_SCHEMA,
)
from orphanet_link.mcp.service_adapters import get_orphanet_service
from orphanet_link.mcp.tools._common import ResponseMode, TermStr

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ClosureLimit = Annotated[int, Field(ge=1, le=1000, description="Max rows returned (default 50).")]
_ClosureOffset = Annotated[
    int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
]


def register_association_tools(mcp: FastMCP) -> None:
    """Register the disease association tools on a FastMCP instance."""

    @mcp.tool(
        name="get_disease_genes",
        title="Get Disease Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_GENES_SCHEMA,
        tags={"disease", "genes"},
        description=(
            "Return gene-disease associations for an Orphanet disorder: gene symbol, "
            "HGNC id, association type, and cross-references (OMIM, Ensembl, etc.). "
            "Signature: get_disease_genes(term, response_mode=)."
        ),
    )
    async def get_disease_genes(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_genes(term, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_genes(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_genes",
            call,
            context=McpErrorContext(
                "get_disease_genes", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_phenotypes",
        title="Get Disease Phenotypes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_PHENOTYPES_SCHEMA,
        tags={"disease", "phenotypes"},
        description=(
            "Return HPO phenotype annotations for an Orphanet disorder: HPO id, term name, "
            "and frequency category. Optionally filter by frequency label. "
            f"Frequency values: {', '.join(HPO_FREQUENCIES[:4])} (and others). "
            "Signature: get_disease_phenotypes(term, frequency=, response_mode=)."
        ),
    )
    async def get_disease_phenotypes(
        term: TermStr,
        frequency: Annotated[
            str | None,
            Field(
                description="Filter by HPO frequency label (e.g. 'Frequent (79-30%)'). "
                "Omit to return all.",
                examples=["Frequent (79-30%)", "Very frequent (99-80%)"],
            ),
        ] = None,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_phenotypes(
                term, frequency=frequency, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_phenotypes(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_phenotypes",
            call,
            context=McpErrorContext(
                "get_disease_phenotypes", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_prevalence",
        title="Get Disease Prevalence",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_PREVALENCE_SCHEMA,
        tags={"disease", "epidemiology"},
        description=(
            "Return prevalence data for an Orphanet disorder: prevalence class, "
            "geographic area, and source reference. "
            "Signature: get_disease_prevalence(term, response_mode=)."
        ),
    )
    async def get_disease_prevalence(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_prevalence(
                term, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_simple_association(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_prevalence",
            call,
            context=McpErrorContext(
                "get_disease_prevalence", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_natural_history",
        title="Get Disease Natural History",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_NATURAL_HISTORY_SCHEMA,
        tags={"disease", "epidemiology"},
        description=(
            "Return natural history data for an Orphanet disorder: age of onset "
            "categories and inheritance patterns. "
            "Signature: get_disease_natural_history(term, response_mode=)."
        ),
    )
    async def get_disease_natural_history(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_natural_history(
                term, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_simple_association(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_natural_history",
            call,
            context=McpErrorContext(
                "get_disease_natural_history",
                arguments={"term": term},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_disease_disability",
        title="Get Disease Disability",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_DISABILITY_SCHEMA,
        tags={"disease", "functional"},
        description=(
            "Return functional consequence (disability) data for an Orphanet disorder: "
            "ability categories affected and severity grades. "
            "Signature: get_disease_disability(term, response_mode=)."
        ),
    )
    async def get_disease_disability(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().get_disease_disability(
                term, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_simple_association(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_disability",
            call,
            context=McpErrorContext(
                "get_disease_disability", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="find_diseases_by_gene",
        title="Find Diseases by Gene",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=FIND_BY_GENE_SCHEMA,
        tags={"disease", "genes", "search"},
        description=(
            "Find all Orphanet disorders associated with an HGNC gene symbol. "
            "Returns {orpha_code, name} per disorder with pagination. "
            "Signature: find_diseases_by_gene(gene_symbol, limit=, offset=, response_mode=)."
        ),
    )
    async def find_diseases_by_gene(
        gene_symbol: Annotated[
            str,
            Field(
                description="HGNC gene symbol, e.g. 'KIF7' or 'HNF1B'.",
                examples=["KIF7", "HNF1B", "BRCA1"],
            ),
        ],
        limit: _ClosureLimit = 50,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().find_diseases_by_gene(
                gene_symbol, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_find_by(payload, "gene_symbol")
            return payload

        return await run_mcp_tool(
            "find_diseases_by_gene",
            call,
            context=McpErrorContext(
                "find_diseases_by_gene",
                arguments={"gene_symbol": gene_symbol},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="find_diseases_by_phenotype",
        title="Find Diseases by Phenotype",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=FIND_BY_PHENOTYPE_SCHEMA,
        tags={"disease", "phenotypes", "search"},
        description=(
            "Find all Orphanet disorders annotated with an HPO term id. "
            "Returns {orpha_code, name} per disorder with pagination. "
            "Signature: find_diseases_by_phenotype(hpo_id, limit=, offset=, response_mode=)."
        ),
    )
    async def find_diseases_by_phenotype(
        hpo_id: Annotated[
            str,
            Field(
                description="HPO term id, e.g. 'HP:0000256'.",
                examples=["HP:0000256", "HP:0001250", "HP:0002015"],
            ),
        ],
        limit: _ClosureLimit = 50,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_orphanet_service().find_diseases_by_phenotype(
                hpo_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_find_by(payload, "hpo_id")
            return payload

        return await run_mcp_tool(
            "find_diseases_by_phenotype",
            call,
            context=McpErrorContext(
                "find_diseases_by_phenotype",
                arguments={"hpo_id": hpo_id},
                response_mode=response_mode,
            ),
        )
