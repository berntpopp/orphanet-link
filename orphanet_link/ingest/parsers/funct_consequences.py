"""Parser for ``en_funct_consequences.xml`` — disability / functional-consequence annotations.

Yields one row per ``<DisabilityDisorderAssociation>`` nested under each
``<Disorder>`` in the ``DisorderDisabilityRelevanceList`` wrapper.
"""

from __future__ import annotations

from pathlib import Path

from . import _common as c


def parse(path: str | Path) -> list[dict]:
    """Parse ``en_funct_consequences.xml`` into disability-annotation rows.

    Args:
        path: Filesystem path to the Orphadata XML file.

    Returns:
        A list of dicts, one per ``DisabilityDisorderAssociation``, each with
        the keys ``orpha_code``, ``annotation``, ``frequency``, ``temporality``,
        and ``severity``.
    """
    rows: list[dict] = []
    for disorder in c.iter_disorders(path, "DisorderDisabilityRelevanceList", item="Disorder"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue
        for assoc in disorder.findall(
            "DisabilityDisorderAssociationList/DisabilityDisorderAssociation"
        ):
            rows.append(
                {
                    "orpha_code": code,
                    "annotation": c.named(assoc, "Disability"),
                    "frequency": c.named(assoc, "FrequenceDisability"),
                    "temporality": c.named(assoc, "TemporalityDisability"),
                    "severity": c.named(assoc, "SeverityDisability"),
                }
            )
    return rows
