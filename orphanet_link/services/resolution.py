"""Resolution cascade: id / xref / label -> canonical ORPHAcode (+ match provenance).

The cascade:
  a. normalize_orpha_code(query) -> if code and get_disorder finds it -> match_type="orpha_code"
  b. parse_curie(query) -> if known prefix: resolve_xref(prefix, local);
     1 hit -> match_type="xref"; >1 -> AmbiguousQueryError
  c. resolve_label(query): exactly 1 distinct code -> match_type="exact_label";
     >1 distinct codes -> AmbiguousQueryError
  d. search(query): exactly 1 hit -> match_type="search"; >1 -> AmbiguousQueryError
     with top candidates; 0 -> NotFoundError

Returns plain data / raises typed exceptions; the MCP envelope owns error shaping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orphanet_link.exceptions import AmbiguousQueryError, NotFoundError
from orphanet_link.identifiers import normalize_orpha_code, parse_curie

if TYPE_CHECKING:
    from orphanet_link.data.repository import OrphanetRepository

#: Maps a lookup ``label_type`` to a resolve ``match_type``.
_LABEL_MATCH_TYPE = {
    "name": "exact_label",
    "synonym": "exact_label",
}

#: Maximum candidates surfaced in ambiguity errors.
_MAX_AMBIGUITY_CANDIDATES = 5


def resolve(repo: OrphanetRepository, query: str) -> dict[str, Any]:
    """Resolve a query string to ``{orpha_code, name, match_type}``.

    Cascade:
    a. normalize_orpha_code(query) -> if code and get_disorder finds it
       -> match_type="orpha_code"
    b. parse_curie(query) -> if known prefix: resolve_xref(prefix, local);
       1 hit -> match_type="xref"; >1 -> AmbiguousQueryError
    c. resolve_label(query): exactly 1 distinct code -> match_type="exact_label";
       >1 distinct codes -> AmbiguousQueryError
    d. search(query): exactly 1 hit -> match_type="search"; >1 ->
       AmbiguousQueryError with top candidates; 0 -> NotFoundError
    """
    raw = (query or "").strip()

    # --- a. ORPHAcode ---
    code = normalize_orpha_code(raw)
    if code is not None:
        record = repo.get_disorder(code)
        if record is not None:
            return {
                "orpha_code": code,
                "name": record["name"],
                "match_type": "orpha_code",
            }
        # Numeric but not found -- fall through to label search
        raise NotFoundError(f"No Orphanet disorder for ORPHA:{code}.")

    # --- b. Known CURIE (xref) ---
    prefix, local = parse_curie(raw)
    if prefix is not None:
        hits = repo.resolve_xref(prefix, local)
        if len(hits) == 1:
            return {
                "orpha_code": hits[0]["orpha_code"],
                "name": hits[0]["name"],
                "match_type": "xref",
            }
        if len(hits) > 1:
            candidates = [
                {"orpha_code": h["orpha_code"], "name": h["name"]}
                for h in hits[:_MAX_AMBIGUITY_CANDIDATES]
            ]
            raise AmbiguousQueryError(
                f"'{raw}' maps to {len(hits)} Orphanet disorders; pick one.",
                candidates=candidates,
            )
        raise NotFoundError(f"No Orphanet disorder cross-references {raw}.")

    # --- c. Exact label ---
    label_hits = repo.resolve_label(raw)
    if label_hits:
        distinct = {h["orpha_code"] for h in label_hits}
        if len(distinct) == 1:
            best = label_hits[0]
            match_type = _LABEL_MATCH_TYPE.get(best.get("label_type", ""), "exact_label")
            return {
                "orpha_code": best["orpha_code"],
                "name": best["name"],
                "match_type": match_type,
            }
        # Multiple distinct codes share the same label
        candidates = _dedupe_candidates(label_hits)
        raise AmbiguousQueryError(
            f"'{raw}' matches {len(distinct)} Orphanet disorders; pick one.",
            candidates=candidates,
        )

    # --- d. FTS search fallback ---
    search_result = repo.search(raw, limit=_MAX_AMBIGUITY_CANDIDATES + 1)
    search_hits = search_result.get("results", [])
    if len(search_hits) == 1:
        hit = search_hits[0]
        return {
            "orpha_code": hit["orpha_code"],
            "name": hit["name"],
            "match_type": "search",
        }
    if len(search_hits) > 1:
        candidates = [
            {"orpha_code": h["orpha_code"], "name": h["name"]}
            for h in search_hits[:_MAX_AMBIGUITY_CANDIDATES]
        ]
        raise AmbiguousQueryError(
            f"'{raw}' matches multiple Orphanet disorders; pick one.",
            candidates=candidates,
        )
    raise NotFoundError(
        f"No Orphanet disorder matches '{raw}'. "
        "Try an ORPHAcode (ORPHA:NNN), a disease label, or a cross-reference CURIE."
    )


def _dedupe_candidates(hits: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build de-duplicated ambiguity candidates."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for h in hits:
        code = h["orpha_code"]
        if code in seen:
            continue
        seen.add(code)
        out.append({"orpha_code": code, "name": h["name"]})
        if len(out) >= _MAX_AMBIGUITY_CANDIDATES:
            break
    return out
