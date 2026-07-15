"""Shared annotated argument types for the Orphanet MCP tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.tools.tool import ToolResult
from pydantic import Field

from orphanet_link.constants import XrefSource
from orphanet_link.services.compose import IncludableSection

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

#: Upper bound on any free-text identifier a caller may send. The longest disease label
#: in Orphanet is well under 200 characters, so this rejects nothing real -- it exists
#: because an UNBOUNDED string is echoed back (in ``query`` and again in
#: ``_meta.next_commands``), so a pasted document costs the caller ~2x its own size in
#: tokens for zero information. Declaring the bound (S5: "where a format is constrained,
#: express it") makes the over-long call unrepresentable rather than merely wasteful:
#: pydantic rejects it before the tool body runs, and the standard invalid_input envelope
#: names the offending parameter WITHOUT echoing its value.
MAX_TERM_CHARS = 256

#: Upper bound for a short structured identifier (an HGNC symbol, an HPO id). Same
#: reasoning as MAX_TERM_CHARS, tighter because the format is tighter.
MAX_SYMBOL_CHARS = 64

QueryStr = Annotated[
    str,
    Field(
        description="A disease label, synonym, or ORPHAcode (ORPHA:166024 or 166024).",
        examples=["Aicardi syndrome", "ORPHA:58", "ORPHA:166024"],
        max_length=MAX_TERM_CHARS,
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
        max_length=MAX_TERM_CHARS,
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
        max_length=MAX_TERM_CHARS,
    ),
]

XrefIdStr = Annotated[
    str,
    Field(
        description="An external cross-reference CURIE (prefix:local), e.g. OMIM/MONDO/ICD-10, "
        "to resolve back to the Orphanet term(s) that map to it.",
        examples=["OMIM:607131", "MONDO:0006516", "ICD-10:Q78.6"],
        max_length=MAX_TERM_CHARS,
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

#: A CLOSED array vocabulary -- the item type is a ``Literal``, so an ``enum`` appears
#: under ``items`` in the advertised schema and pydantic rejects an unrecognised section
#: (e.g. ``["natural_history"]``) with invalid_input BEFORE the tool body runs, instead of
#: it being schema-valid and failing at runtime.
IncludeArg = Annotated[
    list[IncludableSection] | None,
    Field(
        description="Compose extra association sections into the single record "
        "(any of: genes, phenotypes, prevalence, disability) so a full entity needs "
        "one call instead of a per-section fan-out. Omit for the base record only.",
        examples=[["genes", "phenotypes", "prevalence"], ["genes"]],
    ),
]

#: A CLOSED array vocabulary (the xref-source set). Item ``enum`` in the schema, so an
#: unrecognised prefix is rejected with invalid_input rather than silently matching
#: nothing -- ``prefixes=["__BOGUS__"]`` used to return ``count: 0, success: true``,
#: indistinguishable from a disorder with no such cross-references.
PrefixesArg = Annotated[
    list[XrefSource] | None,
    Field(
        description="Restrict the cross-reference sources returned to this subset "
        "(any of the xref sources: OMIM/MONDO/ICD-10/ICD-11/UMLS/GARD/MeSH/MedDRA). "
        "Omit to return every source.",
        examples=[["OMIM", "MONDO"]],
    ),
]
