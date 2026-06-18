"""Parser for ``en_product9_prev.xml`` — epidemiology / prevalence.

Yields one row per ``<Prevalence>`` entry nested under each ``<Disorder>``.
A single disorder may carry multiple prevalence records (different types,
geographic regions, or validation states), so the returned list has one dict
per prevalence item rather than one per disorder.
"""

from __future__ import annotations

from pathlib import Path

from . import _common as c


def parse(path: str | Path) -> list[dict]:
    """Parse ``en_product9_prev.xml`` into one prevalence row per entry.

    Args:
        path: Filesystem path to the Orphadata product-9-prev XML file.

    Returns:
        A list of dicts, each representing one ``<Prevalence>`` element with
        the fields ``orpha_code``, ``prevalence_type``, ``prevalence_class``,
        ``val_moy``, ``geographic``, ``qualification``, ``validation_status``,
        and ``source``.
    """
    rows: list[dict] = []
    for disorder in c.iter_disorders(path, "DisorderList"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        for prev in disorder.findall("PrevalenceList/Prevalence"):
            rows.append(
                {
                    "orpha_code": code,
                    "prevalence_type": c.named(prev, "PrevalenceType"),
                    "prevalence_class": c.named(prev, "PrevalenceClass"),
                    "val_moy": c.to_float(c.text(prev, "ValMoy")),
                    "geographic": c.named(prev, "PrevalenceGeographic"),
                    "qualification": c.named(prev, "PrevalenceQualification"),
                    "validation_status": c.named(prev, "PrevalenceValidationStatus"),
                    "source": c.text(prev, "Source"),
                }
            )
    return rows
