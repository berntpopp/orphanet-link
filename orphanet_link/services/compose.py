"""Compose optional association sections into a get_disease record (P1.1).

``get_disease(include=[...])`` attaches gene/phenotype/prevalence/disability rows
to the single record so a full entity needs one call instead of a per-section
fan-out. Kept out of ``orphanet_service`` to split by responsibility (and budget).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, get_args

from orphanet_link.exceptions import InvalidInputError

#: Sections get_disease can compose via ``include=``. Each is otherwise its own
#: single-item tool; natural_history/classification are already inline in the base
#: record so they are not listed here.
#:
#: A CLOSED vocabulary, and the type is its single source of truth so the advertised
#: schema and the runtime cannot disagree. ``get_disease.include`` used to advertise a
#: bare ``list[str]`` while accepting only these four, so ``include=["natural_history"]``
#: was schema-valid and failed at runtime -- the harmful direction (the model obeys the
#: schema and the call fails). Declaring it as a ``Literal`` puts the enum in the schema.
IncludableSection = Literal["genes", "phenotypes", "prevalence", "disability"]

#: DERIVED from the type above -- never a second hand-maintained copy of the list.
INCLUDABLE: tuple[str, ...] = get_args(IncludableSection)


def compose_sections(repo: Any, code: str, include: Sequence[str]) -> dict[str, Any]:
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
