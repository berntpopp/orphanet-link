"""Foreign identifier forms (genefoundry-router #343): resolve from own data or say why not.

Fixture genes: KIF7 (HGNC 30497, ENSG00000166813, SwissProt Q2M1P5) -> ORPHA:166024.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from orphanet_link.identifiers import classify_gene_id
from tests.unit._envelope import envelope


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    tools = {t.name: t for t in await facade.list_tools()}
    return envelope(await tools[name].fn(**kwargs))


@pytest.mark.parametrize(
    ("value", "form"),
    [
        ("HGNC:30497", "hgnc_id"),
        ("hgnc:30497", "hgnc_id"),
        ("HGNC: 30497", "hgnc_id"),
        ("HGNC_30497", "hgnc_id"),
        ("Q2M1P5-2", "uniprot_accession"),
        ("ENSG00000166813", "ensembl_gene_id"),
        ("ENSG00000166813.12", "ensembl_gene_id"),
        ("Q2M1P5", "uniprot_accession"),
    ],
)
async def test_gene_id_orphanet_carries_resolves_and_is_echoed(
    facade: FastMCP, value: str, form: str
) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol=value)
    assert result["success"] is True
    assert result["gene_symbol"] == "KIF7"
    assert result["resolved_from"] == {"input": value, "form": form, "resolved_to": "KIF7"}
    assert "166024" in [r["orpha_code"] for r in result["results"]]


async def test_symbol_is_untouched_and_unknown_symbol_is_an_honest_empty(facade: FastMCP) -> None:
    known = await _call(facade, "find_diseases_by_gene", gene_symbol="KIF7")
    assert known["success"] is True and "resolved_from" not in known
    for symbol in ("TTN", "B3GAT1"):  # B3GAT1: a real symbol with the UniProt shape
        empty = await _call(facade, "find_diseases_by_gene", gene_symbol=symbol)
        assert empty["success"] is True and empty["total"] == 0


@pytest.mark.parametrize(
    ("value", "first"),
    [
        # A transcript id: hgnc_resolve_symbol cannot convert it, so no converter is named.
        ("ENST00000311936", {"tool": "get_server_capabilities", "arguments": {}}),
        ("NM_004985.5", {"tool": "hgnc_resolve_symbol", "arguments": {"query": "NM_004985.5"}}),
        (
            "NCBIGene:3845",
            {
                "tool": "hgnc_resolve_gene_by_xref",
                "arguments": {"source": "entrez_id", "value": "3845"},
            },
        ),
        (
            "3845",
            {
                "tool": "hgnc_resolve_gene_by_xref",
                "arguments": {"source": "entrez_id", "value": "3845"},
            },
        ),
    ],
)
async def test_gene_id_form_orphanet_lacks_is_invalid_input_with_converter(
    facade: FastMCP, value: str, first: dict[str, Any]
) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol=value)
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "gene_symbol"
    assert result["allowed_values"] and result["hint"]
    assert result["_meta"]["next_commands"][0] == first


@pytest.mark.parametrize("value", ["HGNC:99999999", "ENSG00000000001"])
async def test_accepted_gene_id_absent_from_orphanet_is_not_a_silent_empty(
    facade: FastMCP, value: str
) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol=value)
    assert result["success"] is False
    assert result["error_code"] == "not_found"
    assert result["_meta"]["next_commands"][0] == {
        "tool": "hgnc_resolve_symbol",
        "arguments": {"query": value},
    }


def test_classify_gene_id_leaves_symbols_alone() -> None:
    assert [classify_gene_id(s) for s in ("KRAS", "KIF7", "C9orf72", "HLA-B", "")] == [None] * 5


@pytest.mark.parametrize(
    ("tool", "key"),
    [("resolve_disease", "query"), ("get_disease", "term"), ("get_disease_genes", "term")],
)
async def test_bare_number_miss_names_the_interpretation_and_offers_omim(
    facade: FastMCP, tool: str, key: str
) -> None:
    result = await _call(facade, tool, **{key: "163950"})
    assert result["error_code"] == "not_found"
    assert "ORPHAcode" in result["message"] and "OMIM:163950" in result["message"]
    assert result["_meta"]["next_commands"][0] == {"tool": tool, "arguments": {key: "OMIM:163950"}}


async def test_batch_reports_the_bare_number_per_item(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease_batch", queries=["ORPHA:58", "163950"])
    assert result["success"] is True
    good, bad = result["results"]
    assert good["ok"] is True
    assert bad["ok"] is False and bad["error_code"] == "not_found" and "ORPHAcode" in bad["message"]


async def test_phenotype_label_and_malformed_id_are_invalid_input(facade: FastMCP) -> None:
    label = await _call(facade, "find_diseases_by_phenotype", hpo_id="Macrocephaly")
    assert label["error_code"] == "invalid_input" and label["field"] == "hpo_id"
    assert label["allowed_values"] and label["hint"]
    assert label["_meta"]["next_commands"][0] == {
        "tool": "hpo_resolve_term",
        "arguments": {"query": "Macrocephaly"},
    }
    malformed = await _call(facade, "find_diseases_by_phenotype", hpo_id="HP:000256")
    assert malformed["error_code"] == "invalid_input" and malformed["field"] == "hpo_id"
    assert malformed["_meta"]["next_commands"][0]["tool"] != "find_diseases_by_phenotype"


async def test_single_item_tools_name_their_batch_sibling(facade: FastMCP) -> None:
    tools = {t.name: t.description for t in await facade.list_tools()}
    assert "call resolve_disease_batch once instead" in tools["resolve_disease"]
    assert "call get_disease_batch once instead" in tools["get_disease"]
    assert "OMIM:" in tools["resolve_disease"] and "MONDO:" in tools["resolve_disease"]


async def test_uniprot_accession_on_two_gene_rows_asks_for_one_symbol(
    facade: FastMCP, repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real index: Q16637 is on both SMN1 and SMN2.
    monkeypatch.setattr(
        repo, "gene_symbols", lambda col, _v: ["SMN2", "SMN1"] if col == "swissprot_id" else []
    )
    result = await _call(facade, "find_diseases_by_gene", gene_symbol="Q16637")
    assert result["success"] is False and result["error_code"] == "invalid_input"
    assert result["field"] == "gene_symbol"
    assert result["allowed_values"] == ["SMN1", "SMN2"] and result["hint"]


@pytest.mark.parametrize("value", ["A0A024R161", "B3GAT1"])
async def test_unmatched_uniprot_shape_is_empty_but_points_at_hgnc(
    facade: FastMCP, value: str
) -> None:
    result = await _call(facade, "find_diseases_by_gene", gene_symbol=value)
    assert result["success"] is True and result["total"] == 0
    assert result["_meta"]["next_commands"][0] == {
        "tool": "hgnc_resolve_symbol",
        "arguments": {"query": value},
    }


async def test_long_bare_number_gets_no_omim_offer(facade: FastMCP) -> None:
    result = await _call(facade, "resolve_disease", query="123456789")
    assert result["success"] is False
    assert "OMIM:" not in str(result["_meta"]["next_commands"])


def test_non_latin_digits_are_not_a_gene_id() -> None:
    assert classify_gene_id("\u0661\u0662\u0663") is None
    assert classify_gene_id("HGNC:\u0661\u0662") is None
