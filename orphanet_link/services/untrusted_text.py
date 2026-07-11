"""Response-Envelope v1.1 fencing for the orphanet ``definition`` free-text fields.

Owns the full shape-then-fence lifecycle for every inventory-named upstream
free-text surface so ``orphanet_service.py`` stays within its per-file line
budget. The fencing primitives themselves live untouched in
``orphanet_link/mcp/untrusted_content.py`` (the copied PubTator reference); this
module only wires them to the two existing shaping entry points (``shape``,
``shape_search_hit``).

Fenced surfaces:

- ``get_disease /definition`` (compact/standard/full response modes).
- ``search_diseases /results/*/definition`` (standard/full) **and**
  ``search_diseases /results/*/definition_snippet`` (compact -- the DEFAULT
  search mode, so the most-used path). A search hit carries at most ONE of the
  two (they are mutually exclusive per response_mode), so no single response
  ever duplicates the same prose in two sibling fields.

The invariant used throughout: fence the exact string currently sitting at the
field key, in place -- so ``raw_sha256`` always covers the bytes actually served
(the full definition, or the pre-computed compact snippet), and ``shape`` /
``shape_search_hit`` themselves stay unmodified pure functions.
"""

from __future__ import annotations

from typing import Any

from orphanet_link.mcp.untrusted_content import (
    UntrustedText,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)
from orphanet_link.services.shaping import shape, shape_search_hit

#: Response-Envelope v1.1 untrusted-text provenance label for this backend.
SOURCE = "orphanet"

#: Search-hit keys that may carry externally sourced Orphanet free-text prose.
#: At most ONE is present per hit (response_mode picks it): standard/full ->
#: ``definition``; compact -> ``definition_snippet``.
_SEARCH_TEXT_KEYS: tuple[str, ...] = ("definition", "definition_snippet")


def _fence_field(shaped: dict[str, Any], key: str, *, orpha_code: str) -> UntrustedText | None:
    """Replace ``shaped[key]`` in place with its fenced typed object, if present.

    Fences the exact non-empty string currently at ``key`` (the full definition,
    or the already-computed compact snippet), so ``raw_sha256`` covers the bytes
    actually served. ``record_id`` is the CURIE-style ORPHAcode (e.g.
    ``"ORPHA:558"``), matching the identifier shape used elsewhere in the service.
    No-op (returns ``None``) when the key is absent or its value is not a
    non-empty string (projected out by response_mode/fields, or null).
    """
    raw = shaped.get(key)
    if not isinstance(raw, str) or not raw:
        return None
    fenced = fence_untrusted_text(raw, source=SOURCE, record_id=f"ORPHA:{orpha_code}")
    shaped[key] = fenced.model_dump(mode="json")
    return fenced


def shape_and_fence_disease(
    payload: dict[str, Any],
    response_mode: str,
    fields: list[str] | None,
    *,
    orpha_code: str,
) -> dict[str, Any]:
    """Shape a ``get_disease`` payload, then fence its ``definition`` in place."""
    shaped = shape(payload, response_mode, fields=fields)
    fenced = _fence_field(shaped, "definition", orpha_code=orpha_code)
    if fenced is not None:
        enforce_untrusted_text_limits([fenced])
    return shaped


def shape_and_fence_search_hits(
    hits: list[dict[str, Any]], response_mode: str
) -> list[dict[str, Any]]:
    """Shape each search hit, then fence its free-text field, enforcing v1.1 limits.

    Fences whichever of ``definition`` / ``definition_snippet`` the shaped hit
    carries (mutually exclusive per response_mode). Every fenced object across the
    whole result page is collected and checked together so the 128-objects /
    8-MiB-total ceilings apply to the response as a whole, not per row.
    """
    results: list[dict[str, Any]] = []
    fenced_objs: list[UntrustedText] = []
    for hit in hits:
        shaped_hit = shape_search_hit(hit, response_mode)
        orpha_code = str(hit.get("orpha_code", ""))
        for key in _SEARCH_TEXT_KEYS:
            fenced = _fence_field(shaped_hit, key, orpha_code=orpha_code)
            if fenced is not None:
                fenced_objs.append(fenced)
        results.append(shaped_hit)
    if fenced_objs:
        enforce_untrusted_text_limits(fenced_objs)
    return results
