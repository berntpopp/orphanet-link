"""Static string resources for MCP instructions and discovery resources."""

from __future__ import annotations

from orphanet_link.constants import (
    MATCH_TYPES,
    ORPHANET_LICENSE,
    PREDICATE_RANK,
    RESEARCH_USE_NOTICE,
)


def render_match_types() -> str:
    """Render the resolve_disease match_type vocabulary from ``MATCH_TYPES``."""
    return " | ".join(MATCH_TYPES)


def render_predicate_ranking() -> str:
    """Render the mapping-relation codes from ``PREDICATE_RANK``, strongest first."""
    codes = [code for code, _ in sorted(PREDICATE_RANK.items(), key=lambda kv: kv[1])]
    return " > ".join(codes)


ORPHANET_SERVER_INSTRUCTIONS = (
    "Orphanet-Link grounds disease work in the Orphanet rare disease database "
    "(orphadata.com). It is backed by a local SQLite index built from Orphadata "
    "XML releases (INSERM / Orphanet), so lookups are fast and offline.\n"
    "- Resolve first: resolve_disease(query=) maps a disease label, synonym, or "
    "ORPHAcode (ORPHA:166024 or 166024) to the canonical {orpha_code, name}. "
    "An ambiguous label returns an ambiguous_query error with candidates.\n"
    "- Record: get_disease(term=) returns the term with definition, synonyms, "
    "and cross-references. search_diseases(query=) is FTS over name/synonyms/definition.\n"
    "- Associations: get_disease_genes, get_disease_phenotypes, "
    "get_disease_prevalence, get_disease_natural_history, get_disease_disability.\n"
    "- Find by: find_diseases_by_gene(gene_symbol=), find_diseases_by_phenotype(hpo_id=).\n"
    "- Hierarchy: get_disease_ancestors / get_disease_descendants (transitive closure); "
    "get_disease_classification (Orphanet classification tree).\n"
    "- Cross-ontology: resolve_xref(xref_id=) maps an external CURIE (OMIM/ICD/MONDO/...) "
    "to the Orphanet term(s); map_cross_ontology(term=) lists a term's external mappings.\n"
    "- Verbosity: most tools take response_mode (minimal | compact | standard | full, "
    "default compact). Discovery: get_server_capabilities or get_diagnostics, "
    "or read orphanet://capabilities / orphanet://tools.\n"
    "- Citation: always cite the ORPHAcode AND the Orphanet data version "
    "(get_diagnostics reports it). Orphadata is CC BY 4.0 (INSERM attribution required). "
    f"{RESEARCH_USE_NOTICE}"
)

ORPHANET_USAGE_NOTES = (
    "Start with resolve_disease to normalise any label/synonym/ORPHAcode to its "
    "canonical term, then get_disease for the record. Fetch gene associations with "
    "get_disease_genes and HPO phenotypes with get_disease_phenotypes. Navigate the "
    "classification tree with get_disease_classification / get_disease_ancestors / "
    "get_disease_descendants. Map across ontologies with resolve_xref (external -> "
    "Orphanet) and map_cross_ontology (Orphanet -> external). "
    "Follow _meta.next_commands to advance without guessing the next tool."
)

ORPHANET_REFERENCE_NOTES = (
    "Error codes (8): invalid_input, not_found, ambiguous_query, data_unavailable, "
    "rate_limited, upstream_unavailable, limit_exceeded, internal_error. match_type on "
    f"resolve_disease is one of {render_match_types()} (strongest first). "
    "Cross-references are ranked by mapping relation: "
    f"{render_predicate_ranking()} (E = exact). Supported xref sources: OMIM, MONDO, "
    "ICD-10, ICD-11, UMLS, GARD, MeSH, MedDRA. The local index is built from Orphadata "
    "XML releases (data source = Orphanet / INSERM); get_diagnostics reports the loaded "
    f"release version and counts. {ORPHANET_LICENSE}"
)

# Keep old names as aliases for backward compat within this package
MONDO_USAGE_NOTES = ORPHANET_USAGE_NOTES
MONDO_REFERENCE_NOTES = ORPHANET_REFERENCE_NOTES
