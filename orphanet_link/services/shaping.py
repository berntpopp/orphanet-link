"""Response-mode projection for Orphanet disease payloads.

``standard`` / ``full`` are the identity (the complete record). ``compact``
(the default) drops null/empty values **recursively** — including inside nested
objects and list-of-dict rows, so a per-row ``diagnostic_criteria: null`` (and
peers) never reaches the wire.

``minimal`` NARROWS A RECORD; IT NEVER DELETES A COLLECTION
-----------------------------------------------------------
Response-Envelope Standard v1 defines ``minimal`` as *"the mandatory envelope plus
**stable identifiers**, omitting all optional record detail"* — identifiers are
explicitly retained. It therefore keeps:

* the identity anchors (``orpha_code`` / ``name`` / ``orphanet_version``);
* **every collection**, with each record projected down to its stable identifier
  fields (see :data:`_ROW_IDENTIFIERS`);
* **every structural scalar** (``count`` / the pagination block) — the ONLY signal
  that tells a caller "this disease genuinely has no genes" apart from "the server
  discarded your payload" (see :data:`_STRUCTURAL_KEYS`).

and drops only optional record *detail* scalars (``definition``, ``disorder_type``…).

This is a fix, not a preference. ``minimal`` used to keep the anchors and nothing
else, so ``get_disease_genes(term, response_mode="minimal")`` answered with an
envelope carrying ``success: true``, no ``genes`` and no ``count`` — byte-identical
to a disorder with no gene associations at all (issue #28). A silent-empty is worse
than an error: the caller cannot even know to retry.

An UNRECOGNISED collection key is kept **whole** rather than dropped
(:func:`_project_records` fails open). A future collection can therefore only ever
be too verbose in ``minimal``; it can never silently vanish — the failure mode that
caused this bug is unrepresentable. ``tests/unit/test_response_mode_records.py``
partitions every collection the tool surface emits into "projected" or "kept whole",
with no third bucket.
"""

from __future__ import annotations

from typing import Any

RESPONSE_MODES: list[str] = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

#: Default cap for the compact search snippet (chars).
SEARCH_SNIPPET_CHARS = 140

_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset(
    {"orpha_code", "name", "orphanet_version", "_meta", "success"}
)

#: The stable identifier fields of a record, per collection key. ``minimal`` projects
#: each record in the collection down to these — the ORPHA/HGNC/HPO ids and the few
#: fields that identify a row that has no id of its own (a prevalence estimate is
#: identified by its type + class + geography; a functional consequence by its ability
#: category + severity). The collection and its ``count`` always survive; only the
#: record's optional DETAIL is dropped.
_ROW_IDENTIFIERS: dict[str, tuple[str, ...]] = {
    "genes": ("gene_symbol", "hgnc_id"),
    "phenotypes": ("hpo_id",),
    "prevalence": ("prevalence_type", "prevalence_class", "geographic"),
    "disability": ("annotation", "severity"),
    "age_of_onset": ("onset",),
    "inheritance": ("inheritance",),
    "parents": ("orpha_code",),
    "children": ("orpha_code",),
    "ancestors": ("orpha_code",),
    "descendants": ("orpha_code",),
    "results": ("orpha_code",),
    "matches": ("orpha_code",),
    #: Grouped by source prefix: ``{"OMIM": [{object_id, …}], …}``. The group key IS
    #: the source, so the entry's identifier is the target id alone.
    "mappings": ("object_id",),
    "xrefs": ("object_id",),
}

#: Collections whose records are bare scalars (``synonyms`` is a list of strings).
#: There is no field to project, so the list is kept verbatim.
_SCALAR_COLLECTIONS: frozenset[str] = frozenset({"synonyms"})

#: Envelope STRUCTURE, not record detail: the zero-vs-N signal and the pagination
#: cursor. Always retained at ``minimal`` — dropping ``count`` is what made a
#: discarded payload indistinguishable from an empty one. The three ``*_filter`` /
#: ``coverage`` echoes are the server telling the caller what it actually applied,
#: and are worth a handful of tokens even in the leanest mode.
_STRUCTURAL_KEYS: frozenset[str] = frozenset(
    {
        "count",
        "total",
        "returned",
        "limit",
        "offset",
        "next_offset",
        "truncated",
        "coverage",
        "frequency_filter",
        "prefixes_filter",
    }
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


def _project_row(row: Any, identifiers: tuple[str, ...] | None) -> Any:
    """Narrow ONE record to its stable identifiers, dropping null/empty fields.

    Fails open: a row in an unregistered collection (``identifiers is None``) is
    returned whole. Being too verbose is a token cost; being empty is a lie.
    """
    if not isinstance(row, dict) or identifiers is None:
        return row
    return {k: row[k] for k in identifiers if k in row and not _is_empty(row[k])}


def _project_records(key: str, value: Any) -> Any:
    """Narrow every record in a collection; the collection itself always survives.

    Handles both shapes the surface emits: a plain list of rows, and a grouped
    object (``{"OMIM": [row, …]}``) whose values are lists of rows.
    """
    if key in _SCALAR_COLLECTIONS:
        return value
    identifiers = _ROW_IDENTIFIERS.get(key)
    if isinstance(value, list):
        return [_project_row(row, identifiers) for row in value]
    if isinstance(value, dict) and all(isinstance(v, list) for v in value.values()):
        return {
            group: [_project_row(row, identifiers) for row in rows] for group, rows in value.items()
        }
    return value


def _is_collection(value: Any) -> bool:
    """True for the two collection shapes: a list, or an object grouping lists."""
    if isinstance(value, list):
        return True
    return (
        isinstance(value, dict) and bool(value) and all(isinstance(v, list) for v in value.values())
    )


def _shape_minimal(record: dict[str, Any], anchors: tuple[str, ...]) -> dict[str, Any]:
    """Keep the envelope, the anchors, every POPULATED collection (narrowed), every count.

    Drops optional record-detail scalars (``definition``, ``disorder_type``, …), and —
    exactly as ``compact`` does — a collection that is empty. Dropping an EMPTY
    collection cannot destroy a record, and it keeps ``minimal`` a strict subset of the
    default response rather than a strangely fatter one. The zero-vs-N signal a caller
    actually reads is ``count``/``total``, which is structural and always retained: a
    disorder with no gene associations answers ``{orpha_code, name, count: 0}``, which
    no longer collides with "the server discarded your payload" — that response is now
    unrepresentable.
    """
    keep = frozenset(anchors) | _PRESERVE_KEYS | _STRUCTURAL_KEYS
    shaped: dict[str, Any] = {}
    for key, value in record.items():
        if key in keep:
            shaped[key] = value
        elif _is_collection(value) and not _is_empty(value):
            shaped[key] = _project_records(key, value)
    return shaped


def shape(
    record: dict[str, Any],
    response_mode: str,
    fields: list[str] | None = None,
    anchors: tuple[str, ...] = ("orpha_code", "name", "orphanet_version"),
) -> dict[str, Any]:
    """Shape a record according to response_mode and optional fields projection.

    - ``minimal``: anchors + every collection (records narrowed to their stable
      identifiers) + every count/pagination field. NEVER deletes a collection.
    - ``compact``: drop null/empty values; identity otherwise.
    - ``standard`` / ``full``: return record as-is (identity).
    - ``fields``: always retain anchors; project to specified fields.
    """
    shaped: dict[str, Any]
    if response_mode == "minimal":
        shaped = _shape_minimal(record, anchors)
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
    """Truncate ``text`` to ``limit`` chars on a word boundary (adds ``…``).

    Internal whitespace (tab/LF/CR) is **preserved**, never collapsed: a
    downstream Response-Envelope v1.1 fence digests this snippet's true
    pre-normalization bytes, and the standard requires tab/LF/CR be kept. Only a
    trailing partial word and any trailing whitespace before the ellipsis are
    trimmed. (Previously this collapsed whitespace runs, which stripped tab/LF/CR
    and made the snippet digest cover rewritten text.)
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    head, sep, _ = cut.rpartition(" ")
    return (head if sep else cut).rstrip() + "…"


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
