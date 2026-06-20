"""Tests for OrphanetService (services/orphanet_service.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.data.repository import OrphanetRepository
from orphanet_link.exceptions import NotFoundError
from orphanet_link.ingest.builder import build_database
from orphanet_link.services.orphanet_service import OrphanetService

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
def svc(tmp_path_factory) -> OrphanetService:
    tmp = tmp_path_factory.mktemp("db_service")
    db = _build(tmp)
    repo = OrphanetRepository(db)
    yield OrphanetService(repo=repo)
    repo.close()


# -- get_disease ---------------------------------------------------------------


def test_get_disease_by_orpha_code(svc):
    result = svc.get_disease("ORPHA:58")
    assert result["orpha_code"] == "58"
    assert result["name"] is not None
    assert len(result["name"]) > 0


def test_get_disease_returns_definition(svc):
    result = svc.get_disease("ORPHA:166024", response_mode="standard")
    assert "definition" in result
    assert result["definition"] is not None


def test_get_disease_fields_projection(svc):
    # ORPHA:166024 has a definition in the fixture
    result = svc.get_disease("ORPHA:166024", response_mode="standard", fields=["definition"])
    assert "orpha_code" in result  # anchor always retained
    assert "name" in result  # anchor always retained
    assert "definition" in result
    assert "synonyms" not in result


def test_get_disease_not_found_raises(svc):
    with pytest.raises(NotFoundError):
        svc.get_disease("ORPHA:9999999")


# -- get_disease_genes ---------------------------------------------------------


def test_get_disease_genes_includes_kif7(svc):
    result = svc.get_disease_genes("ORPHA:166024")
    symbols = [g["gene_symbol"] for g in result["genes"]]
    assert "KIF7" in symbols


def test_get_disease_genes_count(svc):
    result = svc.get_disease_genes("ORPHA:166024")
    assert result["count"] == len(result["genes"])


# -- map_cross_ontology --------------------------------------------------------


def test_map_cross_ontology_groups_omim(svc):
    result = svc.map_cross_ontology("ORPHA:166024")
    assert "OMIM" in result["mappings"]


def test_map_cross_ontology_omim_has_607131(svc):
    result = svc.map_cross_ontology("ORPHA:166024")
    omim_ids = [e["object_id"] for e in result["mappings"]["OMIM"]]
    assert "607131" in omim_ids


def test_map_cross_ontology_prefix_filter(svc):
    result = svc.map_cross_ontology("ORPHA:166024", prefixes=["OMIM"])
    # Only OMIM should be present
    assert "OMIM" in result["mappings"]
    for key in result["mappings"]:
        assert key == "OMIM"


# -- find_diseases_by_gene -----------------------------------------------------


def test_find_diseases_by_gene_kif7(svc):
    result = svc.find_diseases_by_gene("KIF7")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "166024" in codes


def test_find_diseases_by_gene_pagination(svc):
    result = svc.find_diseases_by_gene("KIF7", limit=10, offset=0)
    assert "total" in result
    assert "returned" in result
    assert result["limit"] == 10


# -- get_disease_ancestors -----------------------------------------------------


def test_get_disease_ancestors_includes_156(svc):
    result = svc.get_disease_ancestors("ORPHA:166024")
    codes = [a["orpha_code"] for a in result["ancestors"]]
    assert "156" in codes


def test_get_disease_ancestors_excludes_self(svc):
    result = svc.get_disease_ancestors("ORPHA:166024")
    codes = [a["orpha_code"] for a in result["ancestors"]]
    assert "166024" not in codes


def test_get_disease_ancestors_pagination_fields(svc):
    result = svc.get_disease_ancestors("ORPHA:166024", limit=50)
    assert "total" in result
    assert "returned" in result
    assert "truncated" in result


# -- batch operations ----------------------------------------------------------
# Batch lives in the MCP tool layer (mcp/tools/batch.py), exercised by
# tests/unit/test_tools_e2e.py, test_boundaries.py, and test_batch_recovery.py.
# OrphanetService has no *_batch methods (the divergent unused pair was removed).


# -- get_diagnostics -----------------------------------------------------------


def test_get_diagnostics_index_built(svc):
    diag = svc.get_diagnostics()
    assert diag["index_built"] is True
    assert "orphanet_version" in diag


def test_get_diagnostics_no_repo():
    svc_empty = OrphanetService()
    diag = svc_empty.get_diagnostics()
    assert diag["index_built"] is False


# -- search_diseases -----------------------------------------------------------


def test_search_diseases_returns_results(svc):
    result = svc.search_diseases("Alexander")
    assert len(result["results"]) > 0
    codes = [r["orpha_code"] for r in result["results"]]
    assert "58" in codes


def test_search_diseases_pagination(svc):
    result = svc.search_diseases("Alexander", limit=5)
    assert result["limit"] == 5
    assert "total" in result
    assert "returned" in result


# -- resolve_disease -----------------------------------------------------------


def test_resolve_disease_by_label(svc):
    result = svc.resolve_disease("Alexander disease")
    assert result["orpha_code"] == "58"
    assert result["match_type"] == "exact_label"


def test_resolve_disease_by_xref(svc):
    result = svc.resolve_disease("OMIM:607131")
    assert result["orpha_code"] == "166024"
    assert result["match_type"] == "xref"


# -- get_disease_phenotypes ----------------------------------------------------


def test_get_disease_phenotypes_returns_list(svc):
    result = svc.get_disease_phenotypes("ORPHA:58")
    assert isinstance(result["phenotypes"], list)
    assert result["count"] == len(result["phenotypes"])


# -- get_disease_prevalence ----------------------------------------------------


def test_get_disease_prevalence_returns_list(svc):
    result = svc.get_disease_prevalence("ORPHA:166024")
    assert isinstance(result["prevalence"], list)


# -- get_disease_natural_history -----------------------------------------------


def test_get_disease_natural_history_has_onset(svc):
    result = svc.get_disease_natural_history("ORPHA:166024")
    assert "age_of_onset" in result
    assert "inheritance" in result


# -- get_disease_disability ----------------------------------------------------


def test_get_disease_disability_returns_list(svc):
    result = svc.get_disease_disability("ORPHA:166024", response_mode="standard")
    assert isinstance(result["disability"], list)


# -- get_disease_classification ------------------------------------------------


def test_get_disease_classification_has_parents_children(svc):
    result = svc.get_disease_classification("ORPHA:166024", response_mode="standard")
    assert "parents" in result
    assert "children" in result


# -- get_disease_descendants ---------------------------------------------------


def test_get_disease_descendants_156_includes_166024(svc):
    result = svc.get_disease_descendants("ORPHA:156")
    codes = [d["orpha_code"] for d in result["descendants"]]
    assert "166024" in codes


# -- resolve_xref --------------------------------------------------------------


def test_resolve_xref_finds_166024(svc):
    result = svc.resolve_xref("OMIM:607131")
    codes = [m["orpha_code"] for m in result["matches"]]
    assert "166024" in codes


def test_resolve_xref_invalid_curie_raises(svc):
    from orphanet_link.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        svc.resolve_xref("notacurie")


# -- find_diseases_by_phenotype ------------------------------------------------


def test_find_diseases_by_phenotype(svc):
    result = svc.find_diseases_by_phenotype("HP:0000256")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "58" in codes


def test_find_diseases_by_phenotype_malformed_raises(svc):
    from orphanet_link.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError) as exc:
        svc.find_diseases_by_phenotype("NOT_AN_HPO_ID")
    assert exc.value.field == "hpo_id"


def test_find_diseases_by_phenotype_dropped_digit_raises(svc):
    from orphanet_link.exceptions import InvalidInputError

    # 6 digits (a typo) must be rejected, not silently swallowed as "no matches"
    with pytest.raises(InvalidInputError):
        svc.find_diseases_by_phenotype("HP:000256")


def test_find_diseases_by_phenotype_wellformed_absent_is_empty(svc):
    # well-formed but absent -> success path with total 0 (NOT an error)
    result = svc.find_diseases_by_phenotype("HP:9999999")
    assert result["total"] == 0
    assert result["results"] == []


def test_find_diseases_by_phenotype_normalizes_hpo_prefix(svc):
    # HPO: prefix and HP: prefix must resolve to the same canonical id and match
    result = svc.find_diseases_by_phenotype("HPO:0000256")
    codes = [r["orpha_code"] for r in result["results"]]
    assert "58" in codes
    assert result["hpo_id"] == "HP:0000256"
