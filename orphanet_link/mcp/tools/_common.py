"""Shared annotated argument types for the Orphanet MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

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
        description="An ORPHAcode (ORPHA:166024 or 166024), a disease label/synonym, or an "
        "external xref CURIE that resolves to a single Orphanet term.",
        examples=["ORPHA:166024", "Aicardi syndrome", "OMIM:607131"],
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
