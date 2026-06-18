"""Parser for ``en_product6.xml`` — gene-disorder associations.

Each ``<Disorder>`` may carry a ``<DisorderGeneAssociationList>`` with one or
more ``<DisorderGeneAssociation>`` entries.  Every entry links the disorder to a
``<Gene>`` (with its own cross-references) via an association type and status.

Genes are deduplicated by ``Symbol`` across all disorders so the ``genes`` list
contains at most one record per gene symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orphanet_link import constants

from . import _common as c


@dataclass
class Product6Result:
    """Parsed product-6 rows.

    Attributes:
        genes: One dict per unique gene symbol.  Keys: ``gene_symbol``,
            ``gene_name``, ``gene_type``, ``locus``, plus one ``*_id`` column
            per source in ``constants.GENE_XREF_COLUMN``.
        associations: One dict per disorder-gene pair.  Keys: ``orpha_code``,
            ``gene_symbol``, ``association_type``, ``association_status``,
            ``source_pmids``.
    """

    genes: list[dict] = field(default_factory=list)
    associations: list[dict] = field(default_factory=list)


def _parse_gene(gene_el: object) -> dict:
    """Extract a gene record from a ``<Gene>`` element.

    Args:
        gene_el: The ``<Gene>`` lxml element to parse.

    Returns:
        A dict with ``gene_symbol``, ``gene_name``, ``gene_type``, ``locus``,
        and one ``*_id`` column per entry in ``constants.GENE_XREF_COLUMN``.
    """
    record: dict = {
        "gene_symbol": c.text(gene_el, "Symbol"),
        "gene_name": c.text(gene_el, "Name"),
        "gene_type": c.named(gene_el, "GeneType"),
        "locus": c.text(gene_el, "LocusList/Locus/GeneLocus"),
    }
    # Initialise all xref columns to None so the dict always has consistent keys.
    for col in constants.GENE_XREF_COLUMN.values():
        record[col] = None

    for ext in gene_el.findall("ExternalReferenceList/ExternalReference"):
        source = c.text(ext, "Source")
        reference = c.text(ext, "Reference")
        col = constants.GENE_XREF_COLUMN.get(source)
        if col is not None:
            record[col] = reference

    return record


def parse(path: str | Path) -> Product6Result:
    """Parse ``en_product6.xml`` into gene + association rows.

    Args:
        path: Path to the Orphadata XML file.

    Returns:
        A :class:`Product6Result` containing deduplicated gene records and
        one association row per disorder-gene pair.
    """
    result = Product6Result()
    seen_symbols: set[str] = set()

    for disorder in c.iter_disorders(path, "DisorderList"):
        code = c.text(disorder, "OrphaCode")
        if not code:
            continue

        for assoc_el in disorder.findall("DisorderGeneAssociationList/DisorderGeneAssociation"):
            gene_el = assoc_el.find("Gene")
            if gene_el is None:
                continue

            gene = _parse_gene(gene_el)
            symbol = gene["gene_symbol"]
            if not symbol:
                continue

            if symbol not in seen_symbols:
                seen_symbols.add(symbol)
                result.genes.append(gene)

            result.associations.append(
                {
                    "orpha_code": code,
                    "gene_symbol": symbol,
                    "association_type": c.named(assoc_el, "DisorderGeneAssociationType"),
                    "association_status": c.named(assoc_el, "DisorderGeneAssociationStatus"),
                    "source_pmids": c.text(assoc_el, "SourceOfValidation"),
                }
            )

    return result
