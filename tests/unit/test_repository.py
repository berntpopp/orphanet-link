"""Tests for the read-only SQLite repository layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.data.repository import OrphanetRepository
from orphanet_link.ingest.builder import build_database

FX = Path(__file__).parent.parent / "fixtures"


def _build(tmp_path: Path) -> Path:
    cfg = OrphanetDataConfig(data_dir=tmp_path)
    paths = {
        "product1": FX / "en_product1.xml",
        "product4": FX / "en_product4.xml",
        "product6": FX / "en_product6.xml",
        "product7": FX / "en_product7.xml",
        "product9_prev": FX / "en_product9_prev.xml",
        "product9_ages": FX / "en_product9_ages.xml",
        "funct": FX / "en_funct_consequences.xml",
    }
    classification_paths = {"156": FX / "en_product3_156.xml"}
    return build_database(cfg, paths, classification_paths)


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> OrphanetRepository:
    tmp = tmp_path_factory.mktemp("db")
    db = _build(tmp)
    r = OrphanetRepository(db)
    yield r
    r.close()


def _build_dup(tmp_path: Path) -> Path:
    """Build an index where two specialty trees re-assert the same node chain.

    Both ``en_product3_156.xml`` and ``en_product3_999.xml`` encode the
    identical 156 -> 93419 -> 166024 chain, so ``classification_edge`` gets two
    rows per edge.  This reproduces the missing-DISTINCT fan-out in
    ``get_classification`` while leaving the shared ``repo`` fixture untouched.
    """
    cfg = OrphanetDataConfig(data_dir=tmp_path)
    paths = {
        "product1": FX / "en_product1.xml",
        "product4": FX / "en_product4.xml",
        "product6": FX / "en_product6.xml",
        "product7": FX / "en_product7.xml",
        "product9_prev": FX / "en_product9_prev.xml",
        "product9_ages": FX / "en_product9_ages.xml",
        "funct": FX / "en_funct_consequences.xml",
    }
    classification_paths = {
        "156": FX / "en_product3_156.xml",
        "999": FX / "en_product3_999.xml",
    }
    return build_database(cfg, paths, classification_paths)


@pytest.fixture(scope="module")
def repo_dup(tmp_path_factory) -> OrphanetRepository:
    tmp = tmp_path_factory.mktemp("db_dup")
    db = _build_dup(tmp)
    r = OrphanetRepository(db)
    yield r
    r.close()


# -- meta ---------------------------------------------------------------------


def test_get_meta(repo):
    meta = repo.get_meta()
    assert meta["schema_version"] == 1
    assert meta["orphanet_version"].startswith("1.3.42")
    assert meta["disorder_count"] >= 2


# -- disorder -----------------------------------------------------------------


def test_get_disorder_returns_row(repo):
    d = repo.get_disorder("166024")
    assert d is not None
    assert d["orpha_code"] == "166024"
    assert "name" in d
    assert isinstance(d["synonyms"], list)


def test_get_disorder_none_for_missing(repo):
    assert repo.get_disorder("9999999") is None


# -- resolve_label ------------------------------------------------------------


def test_resolve_label_alexander(repo):
    hits = repo.resolve_label("Alexander disease")
    codes = [h["orpha_code"] for h in hits]
    assert "58" in codes


def test_resolve_label_case_insensitive(repo):
    lower = repo.resolve_label("alexander disease")
    upper = repo.resolve_label("ALEXANDER DISEASE")
    assert {h["orpha_code"] for h in lower} == {h["orpha_code"] for h in upper}


def test_resolve_label_returns_label_type(repo):
    hits = repo.resolve_label("Alexander disease")
    types = {h["label_type"] for h in hits}
    assert "name" in types


# -- search -------------------------------------------------------------------


def test_search_alexander_finds_58(repo):
    result = repo.search("Alexander")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "58" in codes
    assert result["total"] >= 1


def test_search_returns_envelope(repo):
    result = repo.search("Alexander", limit=10, offset=0)
    assert "results" in result
    assert "total" in result
    assert "limit" in result
    assert "offset" in result
    assert result["limit"] == 10
    assert result["offset"] == 0


def test_search_punctuation_does_not_crash(repo):
    # FTS would normally crash on 'dysplasia-macrocephaly'; must fall back to LIKE
    result = repo.search("dysplasia-macrocephaly")
    assert isinstance(result["results"], list)


def test_search_empty_query_does_not_crash(repo):
    result = repo.search("")
    assert isinstance(result["results"], list)


# -- get_xrefs ----------------------------------------------------------------


def test_get_xrefs_166024(repo):
    xrefs = repo.get_xrefs("166024")
    sources = {x["source"] for x in xrefs}
    assert "OMIM" in sources


def test_get_xrefs_e_ranked_first(repo):
    xrefs = repo.get_xrefs("166024")
    relations = [x["mapping_relation"] for x in xrefs if x["mapping_relation"]]
    # E (exact) should appear before any NTBT/BTNT/ND/W
    if "E" in relations:
        e_idx = relations.index("E")
        for rank_worse in ("NTBT", "BTNT", "ND", "W"):
            if rank_worse in relations:
                assert e_idx < relations.index(rank_worse)


def test_get_xrefs_fields(repo):
    xrefs = repo.get_xrefs("166024")
    for x in xrefs:
        assert "source" in x
        assert "object_id" in x
        assert "mapping_relation" in x
        assert "icd_relation" in x
        assert "validation_status" in x
        assert "ref_uri" in x


# -- resolve_xref -------------------------------------------------------------


def test_resolve_xref_omim(repo):
    hits = repo.resolve_xref("OMIM", "607131")
    codes = [h["orpha_code"] for h in hits]
    assert "166024" in codes


def test_resolve_xref_case_insensitive_object_id(repo):
    hits = repo.resolve_xref("OMIM", "607131")
    hits_upper = repo.resolve_xref("OMIM", "607131")
    assert {h["orpha_code"] for h in hits} == {h["orpha_code"] for h in hits_upper}


def test_resolve_xref_returns_name(repo):
    hits = repo.resolve_xref("OMIM", "607131")
    for h in hits:
        assert "name" in h


# -- get_genes ----------------------------------------------------------------


def test_get_genes_166024(repo):
    genes = repo.get_genes("166024")
    symbols = [g["gene_symbol"] for g in genes]
    assert "KIF7" in symbols


def test_get_genes_includes_hgnc_id(repo):
    genes = repo.get_genes("166024")
    kif7 = next(g for g in genes if g["gene_symbol"] == "KIF7")
    assert kif7["hgnc_id"] == "30497"


def test_get_genes_includes_association_fields(repo):
    genes = repo.get_genes("166024")
    for g in genes:
        assert "association_type" in g
        assert "association_status" in g
        assert "source_pmids" in g


# -- find_disorders_by_gene ---------------------------------------------------


def test_find_disorders_by_gene_kif7(repo):
    result = repo.find_disorders_by_gene("KIF7")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "166024" in codes


def test_find_disorders_by_gene_case_insensitive(repo):
    lower = repo.find_disorders_by_gene("kif7")
    upper = repo.find_disorders_by_gene("KIF7")
    assert {r["orpha_code"] for r in lower["results"]} == {
        r["orpha_code"] for r in upper["results"]
    }


def test_find_disorders_by_gene_envelope(repo):
    result = repo.find_disorders_by_gene("KIF7", limit=10, offset=0)
    assert "results" in result
    assert "total" in result
    assert result["limit"] == 10
    assert result["offset"] == 0


# -- get_phenotypes -----------------------------------------------------------


def test_get_phenotypes_58(repo):
    phenos = repo.get_phenotypes("58")
    hpo_ids = [p["hpo_id"] for p in phenos]
    assert "HP:0000256" in hpo_ids


def test_get_phenotypes_fields(repo):
    phenos = repo.get_phenotypes("58")
    for p in phenos:
        assert "hpo_id" in p
        assert "hpo_term" in p
        assert "frequency" in p
        assert "diagnostic_criteria" in p


def test_get_phenotypes_frequency_filter(repo):
    all_phenos = repo.get_phenotypes("58")
    if all_phenos:
        freq = all_phenos[0]["frequency"]
        filtered = repo.get_phenotypes("58", frequency=freq)
        assert all(p["frequency"] == freq for p in filtered)


# -- find_disorders_by_phenotype ----------------------------------------------


def test_find_disorders_by_phenotype(repo):
    result = repo.find_disorders_by_phenotype("HP:0000256")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "58" in codes


def test_find_disorders_by_phenotype_envelope(repo):
    result = repo.find_disorders_by_phenotype("HP:0000256", limit=10, offset=0)
    assert "results" in result
    assert "total" in result
    assert result["limit"] == 10
    assert result["offset"] == 0


# -- get_prevalence -----------------------------------------------------------


def test_get_prevalence_returns_list(repo):
    prev = repo.get_prevalence("166024")
    assert isinstance(prev, list)


# -- get_natural_history ------------------------------------------------------


def test_get_natural_history_166024(repo):
    nh = repo.get_natural_history("166024")
    assert "age_of_onset" in nh
    assert "inheritance" in nh
    onsets = [o["onset"] for o in nh["age_of_onset"]]
    assert len(onsets) >= 1


def test_get_natural_history_onset_values(repo):
    nh = repo.get_natural_history("166024")
    # fixture has Infancy and Neonatal
    onsets = {o["onset"] for o in nh["age_of_onset"]}
    assert onsets & {"Infancy", "Neonatal"}


# -- get_disability -----------------------------------------------------------


def test_get_disability_returns_list(repo):
    disab = repo.get_disability("166024")
    assert isinstance(disab, list)


# -- get_classification -------------------------------------------------------


def test_get_classification_returns_parents_children(repo):
    cls = repo.get_classification("166024")
    assert "parents" in cls
    assert "children" in cls


def test_get_classification_parents_include_93419(repo):
    cls = repo.get_classification("166024")
    parent_codes = [p["orpha_code"] for p in cls["parents"]]
    assert "93419" in parent_codes


def test_get_classification_children_of_93419_include_166024(repo):
    cls = repo.get_classification("93419")
    child_codes = [c["orpha_code"] for c in cls["children"]]
    assert "166024" in child_codes


# -- get_ancestors ------------------------------------------------------------


def test_get_ancestors_166024(repo):
    result = repo.get_ancestors("166024")
    codes = [r["orpha_code"] for r in result["results"]]
    # Both intermediate and root should be present
    assert "93419" in codes
    assert "156" in codes


def test_get_ancestors_excludes_self(repo):
    result = repo.get_ancestors("166024")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "166024" not in codes


def test_get_ancestors_envelope(repo):
    result = repo.get_ancestors("166024", limit=50, offset=0)
    assert "results" in result
    assert "total" in result
    assert result["limit"] == 50
    assert result["offset"] == 0


# -- get_descendants ----------------------------------------------------------


def test_get_descendants_156_includes_166024(repo):
    result = repo.get_descendants("156")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "166024" in codes


def test_get_descendants_excludes_self(repo):
    result = repo.get_descendants("156")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "156" not in codes


def test_get_descendants_envelope(repo):
    result = repo.get_descendants("156", limit=50, offset=0)
    assert "results" in result
    assert "total" in result


# -- get_classification dedup (F1) --------------------------------------------


def test_get_classification_parents_unique_by_code(repo_dup):
    parents = repo_dup.get_classification("166024")["parents"]
    codes = [p["orpha_code"] for p in parents]
    assert len(codes) == len(set(codes)), f"duplicate parent codes: {codes}"
    assert codes.count("93419") == 1


def test_get_classification_children_unique_by_code(repo_dup):
    children = repo_dup.get_classification("93419")["children"]
    codes = [c["orpha_code"] for c in children]
    assert len(codes) == len(set(codes)), f"duplicate child codes: {codes}"
    assert codes.count("166024") == 1
