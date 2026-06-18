"""Parser for ``en_product9_ages.xml`` — natural history: age of onset + inheritance.

Yields flattened rows for ``AverageAgeOfOnset`` and ``TypeOfInheritance`` per
disorder, one row per term.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import _common as c


@dataclass
class Ages:
    """Parsed product-9-ages rows.

    Args:
        onsets: Sequence of ``(orpha_code, onset_name)`` tuples, one per
            ``AverageAgeOfOnset`` entry.
        inheritance: Sequence of ``(orpha_code, mode_name)`` tuples, one per
            ``TypeOfInheritance`` entry.
    """

    onsets: list[tuple[str, str]] = field(default_factory=list)
    inheritance: list[tuple[str, str]] = field(default_factory=list)


def parse(path: str | Path) -> Ages:
    """Parse ``en_product9_ages.xml`` into age-of-onset and inheritance rows.

    Args:
        path: Filesystem path to the Orphadata product-9-ages XML file.

    Returns:
        An :class:`Ages` instance whose ``onsets`` and ``inheritance`` lists
        contain one ``(orpha_code, term)`` tuple per XML entry.
    """
    result = Ages()
    for disorder in c.iter_disorders(path, "DisorderList"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        for onset_el in disorder.findall("AverageAgeOfOnsetList/AverageAgeOfOnset"):
            name_el = onset_el.find("Name")
            if name_el is not None and name_el.text and name_el.text.strip():
                result.onsets.append((code, name_el.text.strip()))

        for inh_el in disorder.findall("TypeOfInheritanceList/TypeOfInheritance"):
            name_el = inh_el.find("Name")
            if name_el is not None and name_el.text and name_el.text.strip():
                result.inheritance.append((code, name_el.text.strip()))

    return result
