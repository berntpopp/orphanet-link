"""Compose optional association sections into a get_disease record (P1.1).

``get_disease(include=[...])`` attaches gene/phenotype/prevalence/disability rows
to the single record so a full entity needs one call instead of a per-section
fan-out. Kept out of ``orphanet_service`` to split by responsibility (and budget).
"""

from __future__ import annotations

from typing import Any

from orphanet_link.exceptions import InvalidInputError

#: Sections get_disease can compose via ``include=``. Each is otherwise its own
#: single-item tool; natural_history/classification are already inline in the base
#: record so they are not listed here.
INCLUDABLE: tuple[str, ...] = ("genes", "phenotypes", "prevalence", "disability")


def compose_sections(repo: Any, code: str, include: list[str]) -> dict[str, Any]:
    """Return the requested ``include`` association sections, fetched from ``repo``.

    Unknown section names raise ``invalid_input`` (``field="include"``, carrying
    ``allowed_values``) so a typo is a recoverable error rather than a silently
    missing section. Sections are returned in the canonical ``INCLUDABLE`` order.
    """
    unknown = [s for s in include if s not in INCLUDABLE]
    if unknown:
        raise InvalidInputError(
            f"include accepts {list(INCLUDABLE)}; unknown section(s): {unknown}.",
            field="include",
            allowed=list(INCLUDABLE),
        )
    wanted = set(include)
    sources = {
        "genes": lambda: repo.get_genes(code),
        "phenotypes": lambda: repo.get_phenotypes(code, None),
        "prevalence": lambda: repo.get_prevalence(code),
        "disability": lambda: repo.get_disability(code),
    }
    return {name: sources[name]() for name in INCLUDABLE if name in wanted}
