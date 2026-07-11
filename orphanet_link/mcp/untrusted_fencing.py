"""Fence orphanet upstream free-text at the MCP serialization boundary.

MCP-plane module: it imports the byte-identical fence primitive from
``mcp/untrusted_content.py`` (MCP -> MCP, no plane crossing). The service/data
plane returns plain-string ``definition`` / ``definition_snippet`` values; this
module reshapes them into Response-Envelope v1.1 ``untrusted_text`` objects as a
service result is serialized into an MCP tool payload, so the data plane keeps no
dependency on the MCP plane.

Callers accumulate every fenced object into one ``collected`` list and run a
single ``enforce_untrusted_text_limits`` pass over it, so the 128-object /
8-MiB-total ceilings bind the WHOLE response (a search page, or a batch), never
per record.
"""

from __future__ import annotations

from typing import Any

from orphanet_link.mcp.untrusted_content import (
    UntrustedText,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)

__all__ = [
    "UntrustedText",
    "enforce_untrusted_text_limits",
    "fence_disease_record",
    "fence_search_hits",
]

#: Response-Envelope v1.1 untrusted-text provenance label for this backend.
SOURCE = "orphanet"

#: Free-text keys that may carry externally sourced Orphanet prose in a search
#: hit. Mutually exclusive per response_mode: standard/full -> ``definition``;
#: compact (the default) -> ``definition_snippet`` (a raw-truncated preview of the
#: SAME prose), so a hit never carries both and no response duplicates the prose.
_SEARCH_TEXT_KEYS: tuple[str, ...] = ("definition", "definition_snippet")


def _fence_field(obj: dict[str, Any], key: str, *, orpha_code: str) -> UntrustedText | None:
    """Replace ``obj[key]`` in place with its fenced typed object, if present.

    Fences the exact non-empty string currently at ``key`` (the full definition,
    or the pre-computed compact snippet), so ``raw_sha256`` covers the bytes
    actually served. ``record_id`` is the CURIE-style ORPHAcode (e.g.
    ``"ORPHA:558"``). No-op when the key is absent or its value is not a non-empty
    string (projected out by response_mode/``fields``, or null).
    """
    raw = obj.get(key)
    if not isinstance(raw, str) or not raw:
        return None
    fenced = fence_untrusted_text(raw, source=SOURCE, record_id=f"ORPHA:{orpha_code}")
    obj[key] = fenced.model_dump(mode="json")
    return fenced


def fence_disease_record(record: dict[str, Any], collected: list[UntrustedText]) -> None:
    """Fence ``record['definition']`` in place; append the fenced object to ``collected``."""
    fenced = _fence_field(record, "definition", orpha_code=str(record.get("orpha_code", "")))
    if fenced is not None:
        collected.append(fenced)


def fence_search_hits(payload: dict[str, Any], collected: list[UntrustedText]) -> None:
    """Fence each ``results[*]`` definition/snippet in place; append each to ``collected``."""
    for hit in payload.get("results", []):
        code = str(hit.get("orpha_code", ""))
        for key in _SEARCH_TEXT_KEYS:
            fenced = _fence_field(hit, key, orpha_code=code)
            if fenced is not None:
                collected.append(fenced)
