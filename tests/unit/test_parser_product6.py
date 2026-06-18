"""Tests for the product6 parser (gene-disorder associations)."""

from __future__ import annotations

from pathlib import Path

from orphanet_link.ingest.parsers import product6

FX = Path(__file__).parent.parent / "fixtures" / "en_product6.xml"


def test_product6_gene_xrefs():
    """KIF7 gene record carries the expected cross-reference IDs."""
    res = product6.parse(FX)
    by_symbol = {g["gene_symbol"]: g for g in res.genes}
    assert "KIF7" in by_symbol
    kif7 = by_symbol["KIF7"]
    assert kif7["hgnc_id"] == "30497"
    assert kif7["ensembl_id"] == "ENSG00000166813"
    assert kif7["omim_id"] == "611254"
    assert kif7["swissprot_id"] == "Q2M1P5"
    assert kif7["reactome_id"] == "R-HSA-5620971"
    assert kif7["clinvar_id"] == "KIF7"
    assert kif7["genatlas_id"] == "KIF7"


def test_product6_gene_locus_and_type():
    """KIF7 gene record carries locus and gene_type."""
    res = product6.parse(FX)
    by_symbol = {g["gene_symbol"]: g for g in res.genes}
    kif7 = by_symbol["KIF7"]
    assert kif7["locus"] == "15q26.1"
    assert kif7["gene_type"] == "gene with protein product"
    assert kif7["gene_name"] == "kinesin family member 7"


def test_product6_gene_no_locus():
    """GFAP gene record with no LocusList yields locus=None."""
    res = product6.parse(FX)
    by_symbol = {g["gene_symbol"]: g for g in res.genes}
    assert "GFAP" in by_symbol
    assert by_symbol["GFAP"]["locus"] is None


def test_product6_association_row():
    """Association for orpha_code 166024 / KIF7 matches expected fields."""
    res = product6.parse(FX)
    assoc = next(
        a for a in res.associations if a["orpha_code"] == "166024" and a["gene_symbol"] == "KIF7"
    )
    assert assoc["source_pmids"] == "22587682[PMID]"
    assert assoc["association_status"] == "Assessed"
    assert assoc["association_type"] == "Disease-causing germline mutation(s) in"


def test_product6_gene_deduplication():
    """A gene seen in multiple disorders appears exactly once in genes list."""
    res = product6.parse(FX)
    symbols = [g["gene_symbol"] for g in res.genes]
    assert symbols.count("KIF7") == 1
    assert symbols.count("GFAP") == 1
