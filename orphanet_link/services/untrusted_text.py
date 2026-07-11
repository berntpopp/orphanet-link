"""Response-Envelope v1.1 fencing for the orphanet ``definition`` free-text field.

Owns the full shape-then-fence lifecycle for the two inventory-named surfaces
(``get_disease /definition`` and ``search_diseases /results/*/definition``) so
``orphanet_service.py`` stays within its per-file line budget. The fencing
primitives themselves live untouched in ``orphanet_link/mcp/untrusted_content.py``
(the copied PubTator reference); this module only wires them to the two
existing shaping entry points (``shape``, ``shape_search_hit``).
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


def fence_definition(raw: str | None, *, orpha_code: str) -> UntrustedText | None:
    """Fence a disorder ``definition`` string, or return ``None`` if absent.

    ``record_id`` is the CURIE-style ORPHAcode (e.g. ``"ORPHA:558"``), matching
    the identifier shape used elsewhere in the service (see ``NotFoundError``).
    """
    if not raw:
        return None
    return fence_untrusted_text(raw, source=SOURCE, record_id=f"ORPHA:{orpha_code}")


def _apply(shaped: dict[str, Any], raw: str | None, *, orpha_code: str) -> UntrustedText | None:
    """Replace ``shaped["definition"]`` in place with its fenced form, if present.

    No-op (returns ``None``) when ``shaped`` carries no ``definition`` key
    (response_mode/fields projected it out) or ``raw`` is empty.
    """
    if "definition" not in shaped:
        return None
    fenced = fence_definition(raw, orpha_code=orpha_code)
    if fenced is not None:
        shaped["definition"] = fenced.model_dump(mode="json")
    return fenced


def shape_and_fence_disease(
    payload: dict[str, Any],
    response_mode: str,
    fields: list[str] | None,
    *,
    orpha_code: str,
) -> dict[str, Any]:
    """Shape a ``get_disease`` payload, then fence its ``definition`` in place."""
    definition_raw = payload.get("definition")
    shaped = shape(payload, response_mode, fields=fields)
    fenced = _apply(shaped, definition_raw, orpha_code=orpha_code)
    if fenced is not None:
        enforce_untrusted_text_limits([fenced])
    return shaped


def shape_and_fence_search_hits(
    hits: list[dict[str, Any]], response_mode: str
) -> list[dict[str, Any]]:
    """Shape each search hit, then fence its ``definition``, enforcing v1.1 limits.

    Every fenced object across the whole result page is collected and checked
    together so the 128-objects/8-MiB-total ceilings apply to the response as a
    whole, not per row.
    """
    results: list[dict[str, Any]] = []
    fenced_objs: list[UntrustedText] = []
    for hit in hits:
        shaped_hit = shape_search_hit(hit, response_mode)
        orpha_code = str(hit.get("orpha_code", ""))
        fenced = _apply(shaped_hit, hit.get("definition"), orpha_code=orpha_code)
        if fenced is not None:
            fenced_objs.append(fenced)
        results.append(shaped_hit)
    if fenced_objs:
        enforce_untrusted_text_limits(fenced_objs)
    return results
