"""Parser for ``en_product1.xml`` — nomenclature + cross-references.

Yields one disorder record per ``<Disorder>`` (name, type, group, synonyms,
definition) and the flattened cross-references (one row per
``<ExternalReference>``), preserving the mapping relation and validation status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import _common as c


@dataclass
class Product1Result:
    """Parsed product-1 rows."""

    disorders: list[dict] = field(default_factory=list)
    xrefs: list[dict] = field(default_factory=list)


def parse(path: str | Path) -> Product1Result:
    """Parse ``en_product1.xml`` into disorder + xref rows."""
    result = Product1Result()
    for disorder in c.iter_disorders(path, "DisorderList"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        definition = None
        text_section = disorder.find(
            "SummaryInformationList/SummaryInformation/TextSectionList/TextSection"
        )
        if text_section is not None:
            definition = c.text(text_section, "Contents")

        flag = None
        flag_el = disorder.find("DisorderFlagList/DisorderFlag")
        if flag_el is not None:
            flag = c.text(flag_el, "Value")

        result.disorders.append(
            {
                "orpha_code": code,
                "name": c.text(disorder, "Name"),
                "disorder_type": c.named(disorder, "DisorderType"),
                "disorder_group": c.named(disorder, "DisorderGroup"),
                "disorder_flag": flag,
                "expert_link": c.text(disorder, "ExpertLink"),
                "synonyms": [
                    s.text.strip()
                    for s in disorder.findall("SynonymList/Synonym")
                    if s.text and s.text.strip()
                ],
                "definition": definition,
            }
        )

        for ext in disorder.findall("ExternalReferenceList/ExternalReference"):
            result.xrefs.append(
                {
                    "orpha_code": code,
                    "source": c.text(ext, "Source"),
                    "object_id": c.text(ext, "Reference"),
                    "mapping_relation": c.relation_code(c.named(ext, "DisorderMappingRelation")),
                    "icd_relation": c.named(ext, "DisorderMappingICDRelation"),
                    "validation_status": c.named(ext, "DisorderMappingValidationStatus"),
                    "ref_uri": c.text(ext, "DisorderMappingICDRefUrl"),
                }
            )
    return result
