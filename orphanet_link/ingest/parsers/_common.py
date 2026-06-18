"""Shared helpers for the Orphadata XML parsers.

All Orphadata files share the ``<JDBOR date= version=>`` root and nest disorders
under a per-product wrapper list. ``iter_disorders`` streams those item elements
with ``lxml.iterparse`` and clears them as it goes, so a 50 MB file never lands
fully in memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from lxml import etree


def iter_disorders(
    path: str | Path, wrapper: str, item: str = "Disorder"
) -> Iterator[etree._Element]:
    """Yield each ``item`` element (default ``Disorder``) under ``wrapper``.

    ``wrapper`` documents the containing list element for readability; iteration
    is driven by the ``item`` tag. Each yielded element is cleared after use,
    along with already-processed previous siblings, to bound memory.
    """
    context = etree.iterparse(
        str(path),
        events=("end",),
        tag=item,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
    )
    for _event, element in context:
        yield element
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]


def text(element: etree._Element, tag: str) -> str | None:
    """Return the stripped text of the (possibly nested) ``tag`` child, or None."""
    child = element.find(tag)
    if child is not None and child.text and child.text.strip():
        return child.text.strip()
    return None


def named(element: etree._Element, tag: str) -> str | None:
    """Return the ``<Name>`` text inside the ``tag`` child (Orphanet's enum shape)."""
    child = element.find(f"{tag}/Name")
    if child is not None and child.text and child.text.strip():
        return child.text.strip()
    return None


def relation_code(name: str | None) -> str | None:
    """Extract the leading token of a mapping-relation Name.

    e.g. ``"E (Exact mapping: ...)"`` -> ``"E"``; ``"NTBT (...)"`` -> ``"NTBT"``.
    """
    if not name:
        return None
    return name.split()[0]


def to_float(value: str | None) -> float | None:
    """Parse a float from Orphanet text, returning None on empty/invalid input."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def jdbor_stamp(path: str | Path) -> tuple[str | None, str | None]:
    """Return ``(date, version)`` from the ``<JDBOR>`` root attributes."""
    for _event, element in etree.iterparse(
        str(path),
        events=("start",),
        tag="JDBOR",
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
    ):
        return element.get("date"), element.get("version")
    return None, None
