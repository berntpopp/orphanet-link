"""Response-mode projection for Orphanet disease payloads.

``standard`` / ``full`` are the identity (the complete record). ``compact``
(the default) drops null/empty values **recursively** — including inside nested
objects and list-of-dict rows, so a per-row ``diagnostic_criteria: null`` (and
peers) never reaches the wire. ``minimal`` keeps only the identity anchors
(``orpha_code`` + ``name`` + ``orphanet_version``).
"""

from __future__ import annotations

from typing import Any

RESPONSE_MODES: list[str] = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

#: Default cap for the compact search snippet (chars).
SEARCH_SNIPPET_CHARS = 140

_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

#: Identity anchors kept in ``minimal`` mode.
_MINIMAL_KEEP: frozenset[str] = frozenset({"orpha_code", "name", "orphanet_version", "_meta"})

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset(
    {"orpha_code", "name", "orphanet_version", "_meta", "success"}
)


def _is_empty(value: Any) -> bool:
    """True for the null/empty values compact mode drops."""
    return value is None or value == [] or value == "" or value == {}


def _compact_value(value: Any) -> Any:
    """Recursively drop null/empty values from dicts, incl. dicts nested in lists.

    Scalars pass through unchanged; list items are cleaned element-wise so a
    per-row ``diagnostic_criteria: null`` (and any other null field) vanishes.
    """
    if isinstance(value, dict):
        return {k: _compact_value(v) for k, v in value.items() if not _is_empty(v)}
    if isinstance(value, list):
        return [_compact_value(item) for item in value]
    return value


def shape(
    record: dict[str, Any],
    response_mode: str,
    fields: list[str] | None = None,
    anchors: tuple[str, ...] = ("orpha_code", "name", "orphanet_version"),
) -> dict[str, Any]:
    """Shape a record according to response_mode and optional fields projection.

    - ``minimal``: keep only anchors (+ any ``_meta``/``success`` keys).
    - ``compact``: drop null/empty values; identity otherwise.
    - ``standard`` / ``full``: return record as-is (identity).
    - ``fields``: always retain anchors; project to specified fields.
    """
    if response_mode == "minimal":
        keep = frozenset(anchors) | _PRESERVE_KEYS
        shaped: dict[str, Any] = {k: v for k, v in record.items() if k in keep}
    elif response_mode in ("standard", "full"):
        shaped = dict(record)
    else:
        # compact: drop null/empty top-level keys, then recurse into the rest so
        # nested rows (e.g. phenotypes) carry no null fields either.
        shaped = {}
        for key, value in record.items():
            if key in _PRESERVE_KEYS:
                shaped[key] = value
                continue
            if _is_empty(value):
                continue
            shaped[key] = _compact_value(value)

    if fields is not None:
        return _select_fields(shaped, fields, anchors)
    return shaped


def _select_fields(
    payload: dict[str, Any],
    fields: list[str],
    anchors: tuple[str, ...],
) -> dict[str, Any]:
    """Project a payload to a caller-requested sparse fieldset.

    Identity/grounding anchors are always retained. Supports top-level keys
    and ONE level of dotting into a grouped object -- e.g. ``"xrefs.OMIM"``
    keeps only the OMIM group under ``xrefs``. Unknown fields are skipped
    (open-world). Returns the payload unchanged when ``fields`` is falsy.
    """
    keep = frozenset(anchors) | _PRESERVE_KEYS
    out: dict[str, Any] = {k: v for k, v in payload.items() if k in keep}
    for field in fields:
        top, _, sub = field.partition(".")
        if sub:
            container = payload.get(top)
            if isinstance(container, dict) and sub in container:
                nested = out.setdefault(top, {})
                if isinstance(nested, dict):
                    nested[sub] = container[sub]
        elif top in payload:
            out[top] = payload[top]
    return out


def shape_search_hit(
    hit: dict[str, Any], mode: str, *, snippet_chars: int = SEARCH_SNIPPET_CHARS
) -> dict[str, Any]:
    """Project a search hit, keeping the hot path token-cheap.

    - ``minimal`` / ``compact``: ``{orpha_code, name, score}`` -- compact adds a
      ``definition_snippet`` (truncated to ``snippet_chars``) when a definition
      exists, but never the full paragraph.
    - ``standard`` / ``full``: identity + score + the complete ``definition``.
    """
    out: dict[str, Any] = {
        "orpha_code": hit.get("orpha_code"),
        "name": hit.get("name"),
        "score": hit.get("score"),
    }
    definition = hit.get("definition")
    if mode in ("standard", "full"):
        if definition:
            out["definition"] = definition
    elif mode == "compact" and definition:
        out["definition_snippet"] = _snippet(definition, snippet_chars)
    return out


def _snippet(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars on a word boundary (adds ``...``)."""
    text = " ".join(text.split())  # normalise whitespace runs
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    head, _, _ = cut.rpartition(" ")
    return (head or cut) + "…"


def group_xrefs(
    xrefs: list[dict[str, Any]],
    prefixes: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group cross-references by source (OMIM, MONDO, ICD-10 …).

    When ``prefixes`` is non-empty, only those sources are retained.
    """
    prefixes_upper: set[str] | None = (
        {p.upper() for p in prefixes if p.strip()} if prefixes else None
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for xref in xrefs:
        source = xref.get("source", "")
        if prefixes_upper is not None and source.upper() not in prefixes_upper:
            continue
        entry: dict[str, Any] = {
            "object_id": xref["object_id"],
            "mapping_relation": xref.get("mapping_relation"),
        }
        if xref.get("icd_relation"):
            entry["icd_relation"] = xref["icd_relation"]
        if xref.get("validation_status"):
            entry["validation_status"] = xref["validation_status"]
        grouped.setdefault(source, []).append(entry)
    return grouped
