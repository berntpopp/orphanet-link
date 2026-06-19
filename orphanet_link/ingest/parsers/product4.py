"""Parser for ``en_product4.xml`` — HPO phenotype associations.

Yields one row per ``<HPODisorderAssociation>`` linking an Orphanet disorder
(identified by its OrphaCode) to an HPO term with an associated frequency
and optional diagnostic criteria flag.
"""

from __future__ import annotations

from pathlib import Path

from . import _common as c


def parse(path: str | Path) -> list[dict[str, str | None]]:
    """Parse ``en_product4.xml`` into HPO disorder association rows.

    Args:
        path: Path to the ``en_product4.xml`` file.

    Returns:
        A list of dicts with keys: ``orpha_code``, ``hpo_id``, ``hpo_term``,
        ``frequency``, ``diagnostic_criteria``.
    """
    rows: list[dict[str, str | None]] = []
    for disorder in c.iter_disorders(path, "HPODisorderSetStatusList", item="Disorder"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        for assoc in disorder.findall("HPODisorderAssociationList/HPODisorderAssociation"):
            hpo_id = c.text(assoc, "HPO/HPOId")
            if not hpo_id:
                continue

            dc_el = assoc.find("DiagnosticCriteria")
            diagnostic_criteria: str | None = None
            if dc_el is not None and dc_el.text and dc_el.text.strip():
                diagnostic_criteria = dc_el.text.strip()

            rows.append(
                {
                    "orpha_code": code,
                    "hpo_id": hpo_id,
                    "hpo_term": c.text(assoc, "HPO/HPOTerm"),
                    "frequency": c.named(assoc, "HPOFrequency"),
                    "diagnostic_criteria": diagnostic_criteria,
                }
            )
    return rows
