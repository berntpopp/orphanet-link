"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps.

The envelope-facing subset (``cmd``, ``widen_cmd``, ``default_error_next_commands``,
``withdrawn_recovery``) is consumed by the error boundary; the per-tool ``after_*``
chainers steer the success path (resolve -> record -> hierarchy -> cross-ontology).
"""

from __future__ import annotations

from typing import Any

from orphanet_link.identifiers import is_orpha_code, parse_curie

#: Generic fill-in for the two context-free discovery tools' next step. The
#: discovery tools have no query context, so they must not emit a concrete disease
#: label (it reads as a fabricated Orphanet answer, F-02); this bracketed token is
#: self-evidently a template the agent replaces with the user's term.
DISCOVERY_PLACEHOLDER_QUERY = "<disease name or ORPHAcode>"


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def page_cmd(tool: str, base_args: dict[str, Any], next_offset: int) -> dict[str, Any]:
    """A ready-to-call step that fetches the NEXT page (advance ``offset`` forward).

    Preferred over ``widen_cmd`` for large closures: it never re-sends rows the
    client already has, where raising ``limit`` re-fetches the whole head.
    """
    return cmd(tool, **{**base_args, "offset": next_offset})


def _more_steps(
    tool: str, base_args: dict[str, Any], payload: dict[str, Any], ceiling: int
) -> list[dict[str, Any]]:
    """Forward-page step (if any) then a widen step, for a truncated list payload."""
    if not payload.get("truncated"):
        return []
    steps: list[dict[str, Any]] = []
    next_offset = payload.get("next_offset")
    if next_offset is not None:
        steps.append(page_cmd(tool, base_args, int(next_offset)))
    steps.append(widen_cmd(tool, base_args, int(payload.get("total", 0)), ceiling))
    return steps


def _get_term_id(payload: dict[str, Any]) -> str | None:
    """Return the canonical term id from a payload (orpha_code preferred, mondo_id fallback)."""
    return payload.get("orpha_code") or payload.get("mondo_id")


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in (
        "resolve_disease",
        "get_disease",
        "map_cross_ontology",
        "get_disease_ancestors",
        "get_disease_descendants",
        "get_disease_genes",
        "get_disease_phenotypes",
        "get_disease_prevalence",
        "get_disease_natural_history",
        "get_disease_disability",
        "get_disease_classification",
    ):
        value = str(arguments.get("term", "") or arguments.get("query", ""))
        prefix, _ = parse_curie(value)
        if prefix is not None:
            return [cmd("resolve_xref", xref_id=value), cmd("search_diseases", query=value)]
        if value and not is_orpha_code(value):
            return [cmd("search_diseases", query=value), cmd("get_server_capabilities")]
    if tool == "resolve_xref":
        value = str(arguments.get("xref_id", ""))
        return [cmd("search_diseases", query=value)] if value else [cmd("get_server_capabilities")]
    if tool == "find_diseases_by_gene":
        value = str(arguments.get("gene_symbol", ""))
        return [cmd("search_diseases", query=value)] if value else [cmd("get_server_capabilities")]
    if tool == "find_diseases_by_phenotype":
        return [cmd("get_server_capabilities")]
    if error_code == "data_unavailable":
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]


def withdrawn_recovery(replaced_by: list[dict[str, str]]) -> list[dict[str, Any]]:
    """After an obsolete-term error: chain to the successor record(s)."""
    targets = [r.get("mondo_id") or r.get("orpha_code") for r in replaced_by if r]
    targets = [t for t in targets if t]
    if not targets:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease", term=t) for t in targets[:2]]


def after_capabilities() -> list[dict[str, Any]]:
    """After get_server_capabilities: start the canonical resolve->record workflow.

    Context-free, so the resolve step carries the generic placeholder rather than a
    canned disease label (F-02); the agent substitutes the user's term.
    """
    return [
        cmd("resolve_disease", query=DISCOVERY_PLACEHOLDER_QUERY),
        cmd("get_diagnostics"),
    ]


def after_resolve_disease(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_disease: open the canonical record, else fall back to search."""
    term_id = _get_term_id(resolution)
    if not term_id:
        return [
            cmd("search_diseases", query=str(resolution.get("query", ""))),
            cmd("get_server_capabilities"),
        ]
    return [cmd("get_disease", term=term_id)]


def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_diseases: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("resolve_disease", query=query), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = _get_term_id(hits[0])
    if top:
        steps.append(cmd("get_disease", term=top))
    steps += _more_steps("search_diseases", {"query": query}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_get_disease(disease: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease: walk up the hierarchy and map across ontologies."""
    term_id = _get_term_id(disease)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [
        cmd("get_disease_genes", term=term_id),
        cmd("get_disease_ancestors", term=term_id),
        cmd("map_cross_ontology", term=term_id),
    ]


def after_ancestors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_ancestors: offer descendants; widen if truncated."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_disease_ancestors", {"term": term_id}, payload, 1000)
    steps.append(cmd("get_disease_descendants", term=term_id))
    return steps


def after_descendants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_descendants: offer ancestors; widen if truncated."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_disease_descendants", {"term": term_id}, payload, 1000)
    steps.append(cmd("get_disease_ancestors", term=term_id))
    return steps


def after_parents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_classification: open the ancestors."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease_ancestors", term=term_id)]


def after_children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_classification: open the descendants."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease_descendants", term=term_id)]


def after_resolve_xref(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_xref: open the top matching Orphanet term; widen if truncated."""
    matches = payload.get("matches", [])
    if not matches:
        return [
            cmd("search_diseases", query=str(payload.get("xref_id", ""))),
            cmd("get_server_capabilities"),
        ]
    steps: list[dict[str, Any]] = []
    top = _get_term_id(matches[0])
    if top:
        steps.append(cmd("get_disease", term=top))
    if payload.get("xref_id"):
        steps += _more_steps("resolve_xref", {"xref_id": payload["xref_id"]}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_cross_ontology(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After map_cross_ontology: walk up the hierarchy, or open the record itself."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease_ancestors", term=term_id), cmd("get_disease", term=term_id)]


def _first_resolved_id(payload: dict[str, Any]) -> str | None:
    """Return the term id of the first successfully resolved item in a batch."""
    for item in payload.get("results", []):
        if item.get("ok") and (_get_term_id(item)):
            return str(_get_term_id(item))
    return None


def after_resolve_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_disease_batch: open the first successfully resolved record."""
    term_id = _first_resolved_id(payload)
    if term_id:
        return [cmd("get_disease", term=term_id)]
    return [cmd("get_server_capabilities")]


def after_get_disease_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_batch: map the first resolved record across ontologies."""
    term_id = _first_resolved_id(payload)
    if term_id:
        return [cmd("map_cross_ontology", term=term_id)]
    return [cmd("get_server_capabilities")]


def after_genes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_genes: open phenotypes and map cross-ontology."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [
        cmd("get_disease_phenotypes", term=term_id),
        cmd("map_cross_ontology", term=term_id),
    ]


def after_phenotypes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_phenotypes: open gene associations."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease_genes", term=term_id), cmd("get_disease_prevalence", term=term_id)]


def after_simple_association(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After a simple association tool: open the full disease record."""
    term_id = _get_term_id(payload)
    if not term_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease", term=term_id)]


def after_find_by(payload: dict[str, Any], lookup_key: str) -> list[dict[str, Any]]:
    """After a find_diseases_by_* tool: open the top hit."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = _get_term_id(hits[0])
    if top:
        steps.append(cmd("get_disease", term=top))
    base = {lookup_key: payload.get(lookup_key, "")}
    steps += _more_steps(
        "find_diseases_by_gene" if "gene_symbol" in base else "find_diseases_by_phenotype",
        base,
        payload,
        1000,
    )
    return steps or [cmd("get_server_capabilities")]
