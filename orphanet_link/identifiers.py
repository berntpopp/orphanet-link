"""Identifier normalization for ORPHAcodes and cross-reference CURIEs."""

from __future__ import annotations

import re

#: Matches an ORPHAcode optionally prefixed by ORPHA:/Orphanet: (case-insensitive).
_ORPHA_RE = re.compile(r"^\s*(?:orpha(?:net)?\s*[:_]?\s*)?(\d{1,7})\s*$", re.IGNORECASE)

#: A CURIE like "OMIM:607131", "ICD-10:Q77.3", "HP:0000256".
_CURIE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9.\-]*)\s*:\s*(.+?)\s*$")

#: An HPO term id: an HP/HPO prefix (case-insensitive) + exactly seven digits.
#: A bare number or a wrong digit count is intentionally NOT matched.
_HPO_RE = re.compile(r"^\s*hpo?\s*[:_]?\s*(\d{7})\s*$", re.IGNORECASE)

#: Known cross-reference prefixes (normalized casing) that ``parse_curie`` should
#: recognize as a real ontology/database prefix rather than free text.
_KNOWN_PREFIXES = {
    "OMIM": "OMIM",
    "MONDO": "MONDO",
    "ICD-10": "ICD-10",
    "ICD10": "ICD-10",
    "ICD-11": "ICD-11",
    "ICD11": "ICD-11",
    "UMLS": "UMLS",
    "GARD": "GARD",
    "MESH": "MeSH",
    "MEDDRA": "MedDRA",
    "HP": "HP",
    "HPO": "HP",
    "HGNC": "HGNC",
}


def normalize_orpha_code(value: str) -> str | None:
    """Return the bare ORPHAcode digits, or ``None`` if ``value`` is not one.

    Accepts ``"166024"``, ``"ORPHA:166024"``, ``"Orphanet:166024"``,
    ``"ORPHA_166024"`` (case-insensitive).
    """
    if not value:
        return None
    match = _ORPHA_RE.match(value)
    return match.group(1) if match else None


def is_orpha_code(value: str) -> bool:
    """True if ``value`` parses as an ORPHAcode."""
    return normalize_orpha_code(value) is not None


def normalize_hpo_id(value: str) -> str | None:
    """Return the canonical ``HP:NNNNNNN`` form, or ``None`` if not a valid HPO id.

    Accepts ``"HP:0000256"``, ``"HPO:0000256"``, ``"HP_0000256"``, ``"HP0000256"``
    (case-insensitive, surrounding whitespace ignored). Requires the ``HP``/``HPO``
    prefix and exactly seven digits, so a typo such as ``"HP:000256"`` (a dropped
    digit) or a bare number is rejected rather than silently treated as a miss.
    """
    if not value:
        return None
    match = _HPO_RE.match(value)
    return f"HP:{match.group(1)}" if match else None


def parse_curie(value: str) -> tuple[str | None, str]:
    """Split ``value`` into ``(prefix, local_id)``.

    Returns ``(None, value)`` when ``value`` carries no recognized cross-reference
    prefix (i.e. it is free-text or a bare ORPHAcode). The returned prefix is
    normalized to its canonical casing (e.g. ``"mesh"`` -> ``"MeSH"``).
    """
    if not value:
        return None, value
    match = _CURIE_RE.match(value)
    if not match:
        return None, value.strip()
    raw_prefix, local = match.group(1), match.group(2).strip()
    canonical = _KNOWN_PREFIXES.get(raw_prefix.upper())
    if canonical is None:
        return None, value.strip()
    return canonical, local
