"""Parser for ``en_product7.xml`` — linearisation (preferential parent).

Each ``<Disorder>`` maps to its single preferred parent via
``DisorderDisorderAssociationList/DisorderDisorderAssociation/TargetDisorder``.
Root disorders (no associations) yield a row with ``parent_code=None``.
A disorder with multiple associations produces one row per association.
"""

from __future__ import annotations

from pathlib import Path

from . import _common as c


def parse(path: str | Path) -> list[dict]:
    """Parse ``en_product7.xml`` into linearisation rows.

    Args:
        path: Filesystem path to the Orphadata product-7 XML file.

    Returns:
        A list of dicts, each with keys ``orpha_code`` (str) and
        ``parent_code`` (str | None).  Root nodes have ``parent_code=None``.
        A disorder with multiple associations produces one row per association.
    """
    rows: list[dict] = []
    for disorder in c.iter_disorders(path, "DisorderList"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        associations = disorder.findall(
            "DisorderDisorderAssociationList/DisorderDisorderAssociation"
        )
        if not associations:
            rows.append({"orpha_code": code, "parent_code": None})
        else:
            for assoc in associations:
                parent_el = assoc.find("TargetDisorder/OrphaCode")
                parent_code = (
                    parent_el.text.strip()
                    if parent_el is not None and parent_el.text and parent_el.text.strip()
                    else None
                )
                rows.append({"orpha_code": code, "parent_code": parent_code})

    return rows
