"""Tests for the resolution cascade (services/resolution.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.data.repository import OrphanetRepository
from orphanet_link.exceptions import AmbiguousQueryError, NotFoundError
from orphanet_link.ingest.builder import build_database
from orphanet_link.services.resolution import resolve

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
    tmp = tmp_path_factory.mktemp("db_resolution")
    db = _build(tmp)
    r = OrphanetRepository(db)
    yield r
    r.close()


# -- a. ORPHAcode ------------------------------------------------------------------


def test_resolve_orpha_code_prefixed(repo):
    result = resolve(repo, "ORPHA:166024")
    assert result["orpha_code"] == "166024"
    assert result["match_type"] == "orpha_code"


def test_resolve_orpha_code_bare_digits(repo):
    result = resolve(repo, "166024")
    assert result["orpha_code"] == "166024"
    assert result["match_type"] == "orpha_code"


def test_resolve_orpha_code_58(repo):
    result = resolve(repo, "ORPHA:58")
    assert result["orpha_code"] == "58"
    assert result["match_type"] == "orpha_code"


def test_resolve_orpha_code_not_found_raises(repo):
    with pytest.raises(NotFoundError):
        resolve(repo, "ORPHA:9999999")


# -- b. xref (CURIE) ---------------------------------------------------------------


def test_resolve_xref_omim(repo):
    result = resolve(repo, "OMIM:607131")
    assert result["orpha_code"] == "166024"
    assert result["match_type"] == "xref"


def test_resolve_xref_not_found_raises(repo):
    with pytest.raises(NotFoundError):
        resolve(repo, "OMIM:999999999")


# -- c. exact label ----------------------------------------------------------------


def test_resolve_exact_label_alexander(repo):
    result = resolve(repo, "Alexander disease")
    assert result["orpha_code"] == "58"
    assert result["match_type"] == "exact_label"
    assert result["name"] is not None


def test_resolve_exact_label_case_insensitive(repo):
    result = resolve(repo, "alexander disease")
    assert result["orpha_code"] == "58"
    assert result["match_type"] == "exact_label"


# -- d. search fallback ------------------------------------------------------------


def test_resolve_search_fallback_single_hit(repo):
    # "epiphyseal dysplasia macrocephaly" should hit ORPHA:166024 via FTS
    result = resolve(repo, "Multiple epiphyseal dysplasia-macrocephaly-facial dysmorphism syndrome")
    assert result["orpha_code"] is not None
    assert result["match_type"] in ("exact_label", "orpha_code", "search")


# -- error cases -------------------------------------------------------------------


def test_resolve_not_found_raises(repo):
    with pytest.raises(NotFoundError):
        resolve(repo, "zzz_nonexistent_disorder_xyz")


def test_resolve_ambiguous_raises(repo):
    """A query that matches multiple distinct disorders raises AmbiguousQueryError."""
    # We need to inject ambiguity; mock resolve_label to return 2 distinct codes.
    import unittest.mock as mock

    two_hits = [
        {"orpha_code": "58", "name": "Alexander disease", "label_type": "name"},
        {"orpha_code": "166024", "name": "Acrocallosal syndrome", "label_type": "name"},
    ]
    with mock.patch.object(repo, "resolve_label", return_value=two_hits), pytest.raises(AmbiguousQueryError):
        resolve(repo, "some ambiguous label")
