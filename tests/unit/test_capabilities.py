"""Contract tests for the discovery surface (capabilities payload).

The capabilities payload is the authority a cold client trusts to self-configure.
Every vocabulary fact (match types, predicate ranking) must be rendered from its
constant in constants.py so the payload cannot drift or contradict itself.
"""

from __future__ import annotations

import json

from orphanet_link.constants import MATCH_TYPES, PREDICATE_RANK
from orphanet_link.mcp.capabilities import build_capabilities

#: SSSOM mapping-predicate vocabulary -- WRONG for this Orphanet-backed server.
_SSSOM_TOKENS = ("exactMatch", "equivalentTo", "closeMatch", "narrowMatch", "broadMatch")

#: Stale match_type vocabulary that must no longer appear anywhere in the payload.
_STALE_MATCH_TYPE_TOKENS = ("primary", "exact_synonym", "related_synonym", "orpha_id")


def _payload_json() -> str:
    """Serialize the full capabilities payload to a single JSON text blob."""
    return json.dumps(build_capabilities(), sort_keys=True, default=str)


def test_no_sssom_predicate_vocabulary() -> None:
    """No SSSOM predicate token may appear anywhere in the payload."""
    blob = _payload_json()
    for token in _SSSOM_TOKENS:
        assert token not in blob, f"SSSOM token {token!r} must not appear in capabilities payload"


def test_predicate_ranking_rendered_from_constant() -> None:
    """predicate_ranking prose must list PREDICATE_RANK codes in rank order."""
    payload = build_capabilities()
    prose = payload["predicate_ranking"]
    codes_in_rank_order = [code for code, _ in sorted(PREDICATE_RANK.items(), key=lambda kv: kv[1])]
    assert codes_in_rank_order == ["E", "NTBT", "BTNT", "ND", "W"]
    positions = []
    for code in codes_in_rank_order:
        idx = prose.find(code)
        assert idx != -1, f"predicate code {code!r} must appear in predicate_ranking prose"
        positions.append(idx)
    assert positions == sorted(positions), (
        f"predicate codes must appear in rank order in prose; got positions {positions}"
    )


def test_no_stale_match_type_tokens() -> None:
    """No stale match_type token may appear anywhere in the payload."""
    blob = _payload_json()
    for token in _STALE_MATCH_TYPE_TOKENS:
        assert token not in blob, f"stale match_type token {token!r} must not appear in payload"


def test_match_types_consistent() -> None:
    """Every MATCH_TYPES value appears in match_types; notes/semantics reuse the same set."""
    payload = build_capabilities()
    assert list(payload["match_types"]) == list(MATCH_TYPES)
    for value in MATCH_TYPES:
        assert value in payload["match_type_semantics"], (
            f"match_type {value!r} must be referenced by match_type_semantics"
        )
        assert value in payload["notes"], f"match_type {value!r} must be referenced by notes"


def test_not_found_contract_does_not_overpromise_obsolete() -> None:
    """F6: the index ingests no obsolescence/successor data, so the discovery surface
    must NOT promise an obsolete-ORPHAcode -> not_found + replaced_by behavior it can
    never produce (resolve() never raises it; is_obsolete is always 0)."""
    payload = build_capabilities()
    contract = payload["not_found_contract"].lower()
    assert "replaced_by" not in contract, "must not advertise an unimplemented replaced_by contract"
    assert "not currently surfaced" in contract, "must honestly state obsolescence is not surfaced"
