"""Shared annotated argument types for the Orphanet MCP tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.tools.tool import ToolResult
from pydantic import Field

#: What every tool body returns. The happy path is the plain envelope dict (FastMCP
#: serialises it into ``structuredContent``); the ERROR path is a ``ToolResult`` so the
#: envelope can also carry MCP's ``isError: true``. A returned dict can never set
#: ``isError``, and a client that branches on it would read an error envelope as a
#: SUCCESSFUL call -- see :func:`orphanet_link.mcp.envelope.run_mcp_tool`.
ToolReturn = dict[str, Any] | ToolResult

ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal|compact|standard|full (default compact)."),
]

QueryStr = Annotated[
    str,
    Field(
        description="A disease label, synonym, or ORPHAcode (ORPHA:166024 or 166024).",
        examples=["Aicardi syndrome", "ORPHA:58", "ORPHA:166024"],
    ),
]

TermStr = Annotated[
    str,
    Field(
        description="An ORPHAcode (ORPHA:33069 or 33069), a disease label/synonym, or an "
        "external xref CURIE that resolves to a single Orphanet term.",
        # The first example is what a model copies AND what the fleet behaviour gate uses
        # to build its control call, so it names a disorder that is richly annotated in
        # Orphanet (Dravet syndrome: genes, phenotypes, prevalence, functional
        # consequences, classification). A sparsely-annotated example teaches a model
        # less and leaves the gate probing empty result sets, which prove nothing.
        # The three forms a term may take are all shown.
        examples=["ORPHA:33069", "ORPHA:166024", "Dravet syndrome", "OMIM:607131"],
    ),
]

#: A term for the DESCENDANT walk. Only a grouping/category term HAS descendants -- a
#: specific disease is a leaf -- so this example names one. Handing the model a leaf
#: disease here teaches it to expect rows that can never exist.
GroupingTermStr = Annotated[
    str,
    Field(
        description="An ORPHAcode, label, or xref CURIE for a grouping/category term "
        "(a specific disease is a leaf and has no descendants).",
        examples=["ORPHA:699645", "ORPHA:156", "Variable age-onset epilepsy syndrome"],
    ),
]

XrefIdStr = Annotated[
    str,
    Field(
        description="An external cross-reference CURIE (prefix:local), e.g. OMIM/MONDO/ICD-10, "
        "to resolve back to the Orphanet term(s) that map to it.",
        examples=["OMIM:607131", "MONDO:0006516", "ICD-10:Q78.6"],
    ),
]

FieldsArg = Annotated[
    list[str] | None,
    Field(
        description="Sparse fieldset: return ONLY these top-level keys (dot into a grouped "
        "object, e.g. 'xrefs.OMIM'). Identity anchors (orpha_code, name, orphanet_version) are "
        "always included. Omit for the full payload.",
        examples=[["xrefs.OMIM"], ["definition", "genes"]],
    ),
]

IncludeArg = Annotated[
    list[str] | None,
    Field(
        description="Compose extra association sections into the single record "
        "(any of: genes, phenotypes, prevalence, disability) so a full entity needs "
        "one call instead of a per-section fan-out. Omit for the base record only.",
        examples=[["genes", "phenotypes", "prevalence"], ["genes"]],
    ),
]
