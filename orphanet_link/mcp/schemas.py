"""JSON output schemas for the typed Orphanet MCP tools (MCP structured output).

The schemas are deliberately **permissive** (``additionalProperties: true``,
nothing ``required``) because ``response_mode`` projects fields out and the error
envelope is returned by the same tool body and must also validate.
"""

from __future__ import annotations

from typing import Any

_META = {"type": "object", "additionalProperties": True}


def _envelope(**properties: Any) -> dict[str, Any]:
    """A permissive object schema carrying the common envelope keys + extras."""
    props: dict[str, Any] = {
        "success": {"type": "boolean"},
        "_meta": _META,
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "recovery_action": {"type": "string"},
        "field": {"type": "string"},
        "allowed_values": {"type": "array"},
        "hint": {"type": "string"},
        "candidates": {"type": "array"},
        **properties,
    }
    return {"type": "object", "additionalProperties": True, "properties": props}


_STR = {"type": "string"}
_STR_NULL = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_ARR = {"type": "array"}
_ARR_NULL = {"type": ["array", "null"]}
_OBJ = {"type": "object", "additionalProperties": True}

#: A Response-Envelope v1.1 fenced externally sourced free-text field (typed
#: object, not a bare string) -- see orphanet_link/mcp/untrusted_content.py.
#: ``kind`` is the schema literal; the raw/sanitized prose is never duplicated
#: in a sibling field. Nullable: the upstream source may have no definition for
#: a given record, mirroring ``_STR_NULL``'s ``type`` array idiom.
_UNTRUSTED_TEXT_NULL = {
    "type": ["object", "null"],
    "additionalProperties": True,
    "properties": {
        "kind": {"type": "string", "const": "untrusted_text"},
        "text": _STR,
        "provenance": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "source": _STR,
                "record_id": _STR,
                "retrieved_at": _STR,
            },
        },
        "raw_sha256": _STR,
    },
}

#: One cross-reference target within a prefix group: ONE entry per object_id. The
#: primary ``predicate``/``origin`` are the strongest mapping's; ``predicates`` lists
#: all of them (strongest-first) only when a target is asserted more than once;
#: ``name`` is the target term's label (SSSOM only) when known; ``source`` (the
#: mapping justification) is present only when non-null.
_XREF_ENTRY = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "object_id": _STR,
        "name": _STR,
        "predicate": _STR,
        "predicates": _ARR,
        "origin": _STR,
        "source": _STR_NULL,
    },
}

#: Cross-references grouped by target prefix: ``{"OMIM": [entry, ...], ...}``.
#: Declared as an object (NOT an array) so the grouped payload validates against
#: its own schema -- the historical leak was declaring this shape as ``array``.
_GROUPED_XREFS = {
    "type": "object",
    "additionalProperties": {"type": "array", "items": _XREF_ENTRY},
}

CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    capabilities_version=_STR,
    orphanet_version=_STR,
    tools=_ARR,
    response_modes=_ARR,
    error_codes=_ARR,
)

DIAGNOSTICS_SCHEMA = _envelope(
    data_available=_BOOL,
    orphanet_version=_STR_NULL,
    term_count=_INT,
    obsolete_count=_INT,
    xref_count=_INT,
    mapping_count=_INT,
    schema_version=_INT,
    built_utc=_STR,
    build=_OBJ,
    runtime=_OBJ,
)

RESOLVE_DISEASE_SCHEMA = _envelope(
    query=_STR,
    orpha_code=_STR_NULL,
    name=_STR_NULL,
    definition=_STR_NULL,
    match_type=_STR_NULL,
    obsolete=_BOOL,
    orphanet_version=_STR_NULL,
)

_SEARCH_HIT = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "orpha_code": _STR,
        "name": _STR,
        "score": {"type": "number"},
        # Both are the same upstream free-text surface, fenced as v1.1 untrusted_text.
        # Mutually exclusive per response_mode: standard/full -> definition;
        # compact (the default) -> definition_snippet.
        "definition": _UNTRUSTED_TEXT_NULL,
        "definition_snippet": _UNTRUSTED_TEXT_NULL,
    },
}

SEARCH_SCHEMA = _envelope(
    query=_STR,
    include_obsolete=_BOOL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    results={"type": "array", "items": _SEARCH_HIT},
)

DISEASE_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR,
    definition=_UNTRUSTED_TEXT_NULL,
    synonyms=_ARR,
    xrefs=_GROUPED_XREFS,
    parents=_ARR,
    children=_ARR,
    top_groupings=_ARR,
    subsets=_ARR,
    obsolete=_BOOL,
    match_type=_STR_NULL,
    orphanet_version=_STR_NULL,
    #: Optional composed sections attached when ``include=`` is passed (P1.1).
    genes=_ARR,
    phenotypes=_ARR,
    prevalence=_ARR,
    disability=_ARR,
)

ANCESTORS_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    ancestors=_ARR,
)

DESCENDANTS_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    descendants=_ARR,
)

PARENTS_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    parents=_ARR,
)

CHILDREN_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    children=_ARR,
)

RESOLVE_XREF_SCHEMA = _envelope(
    xref_id=_STR,
    normalized=_STR_NULL,
    prefix=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    matches=_ARR,
)

CROSS_ONTOLOGY_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    mappings=_GROUPED_XREFS,
    count=_INT,
    prefixes_filter=_ARR_NULL,
    orphanet_version=_STR_NULL,
)

#: One result row in a batch response: either a resolved/fetched record (``ok``
#: true, plus the single-tool keys) or a per-item failure (``ok`` false, with its
#: own ``error_code``/``message``). Permissive (``additionalProperties: true``) so
#: a record's projected fields -- including a grouped ``xrefs`` object -- validate.
_BATCH_ITEM = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "query": _STR,
        "term": _STR,
        "index": _INT,
        "ok": _BOOL,
        "orpha_code": _STR_NULL,
        "name": _STR_NULL,
        "match_type": _STR_NULL,
        # A get_disease_batch record mirrors get_disease: its definition is the
        # same v1.1 untrusted_text object (kind const), never a bare string.
        "definition": _UNTRUSTED_TEXT_NULL,
        "error_code": _STR,
        "message": _STR,
        #: Recovery candidates on an ambiguous (or suggestion-bearing) failed item.
        "candidates": _ARR,
    },
}

BATCH_RESOLVE_SCHEMA = _envelope(
    count=_INT,
    results={"type": "array", "items": _BATCH_ITEM},
)

BATCH_DISEASE_SCHEMA = _envelope(
    count=_INT,
    results={"type": "array", "items": _BATCH_ITEM},
)

# ---------------------------------------------------------------------------
# Orphanet-specific schemas
# ---------------------------------------------------------------------------

DISEASE_GENES_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    genes=_ARR,
)

DISEASE_PHENOTYPES_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    frequency_filter=_STR_NULL,
    phenotypes=_ARR,
)

DISEASE_PREVALENCE_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    prevalence=_ARR,
)

DISEASE_NATURAL_HISTORY_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    age_of_onset=_ARR,
    inheritance=_ARR,
)

DISEASE_DISABILITY_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    count=_INT,
    #: "present" when Orphadata records functional consequences, "none" when it does
    #: not (a valid, common state -- never an error). See get_disease_disability.
    coverage=_STR,
    disability=_ARR,
)

DISEASE_CLASSIFICATION_SCHEMA = _envelope(
    orpha_code=_STR,
    name=_STR_NULL,
    parents=_ARR,
    children=_ARR,
)

FIND_BY_GENE_SCHEMA = _envelope(
    gene_symbol=_STR,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    results=_ARR,
)

FIND_BY_PHENOTYPE_SCHEMA = _envelope(
    hpo_id=_STR,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    results=_ARR,
)
