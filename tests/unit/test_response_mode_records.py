"""Contract: ``response_mode`` narrows a RECORD; it never deletes a COLLECTION.

Response-Envelope Standard v1 defines the leanest mode as *"the mandatory envelope
(success, _meta, recommended_citation, unsafe_for_clinical_use) **plus stable
identifiers**, omitting all optional record detail"*. Identifiers are explicitly
RETAINED. A mode that turns N records into zero is a silent-empty by another name:
the caller cannot distinguish "this disease has no associated genes" from "the
server threw your payload away", and ``success: true`` asserts the former.

That is exactly what orphanet-link shipped (issue #28): ``response_mode="minimal"``
kept only the identity anchors, so ``get_disease_genes``/``_phenotypes``/
``_prevalence``/``_natural_history``/``_classification``/``_ancestors`` (and every
other shaped tool) returned the envelope with the payload deleted and no ``count``.

The invariant enforced here, for EVERY registered tool at EVERY response_mode:

    for every collection the default call returns,
        the same collection is present, with the SAME NUMBER OF RECORDS,
        and each record's fields are a SUBSET of the default record's fields.

Fewer fields per record: yes, that is what the mode is for. Fewer records: never.

The tool list and the call arguments are both DERIVED — the tools come from the
registry and the arguments are built from each tool's own advertised ``examples``
(the same fixture the Tool-Schema Documentation Standard S2/S3 exist to provide, and
the same construction the fleet behaviour gate uses). A hardcoded list of the six
tools the audit happened to catch would be the same bug one level up: the seventh
tool would ship ungated.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import FastMCP

from orphanet_link.mcp.facade import create_orphanet_mcp
from orphanet_link.services.shaping import RESPONSE_MODES
from tests.unit._envelope import envelope


def _registered_tool_names() -> list[str]:
    """Every tool the facade registers (collection-time, so each is its own test case)."""
    mcp = create_orphanet_mcp()
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


TOOL_NAMES = _registered_tool_names()


def _records(value: Any) -> list[Any] | None:
    """The records in a collection value, or None when the value is not a collection.

    A collection is a list of records, or a grouped object whose values are all lists
    (``map_cross_ontology.mappings`` / ``get_disease.xrefs`` group their rows by
    source prefix). Counting the grouped shape matters: the behaviour gate only looks
    at lists, so a grouped payload could be silently deleted and still show green.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and value and all(isinstance(v, list) for v in value.values()):
        return [row for rows in value.values() for row in rows]
    return None


def _collections(payload: dict[str, Any]) -> dict[str, list[Any]]:
    """Every record collection in a payload, keyed by its payload key."""
    found: dict[str, list[Any]] = {}
    for key, value in payload.items():
        if key.startswith("_"):
            continue
        records = _records(value)
        if records is not None:
            found[key] = records
    return found


def _fields(record: Any) -> set[str]:
    return set(record) if isinstance(record, dict) else set()


async def _tool(facade: FastMCP, name: str) -> Any:
    return next(t for t in await facade.list_tools() if t.name == name)


def _example_args(tool: Any, index: int = 0) -> dict[str, Any] | None:
    """Build a call from the tool's OWN advertised ``examples`` (S2), by example index.

    None when a required parameter carries no example — the tool is then unprobeable
    here for the same reason the behaviour gate reports it UNGATED, and
    :func:`test_every_tool_is_probeable_from_its_own_examples` fails on it.
    """
    schema = dict(getattr(tool, "parameters", None) or {})
    props = schema.get("properties") or {}
    args: dict[str, Any] = {}
    for name in schema.get("required") or []:
        examples = (props.get(name) or {}).get("examples")
        if not examples:
            return None
        args[name] = examples[min(index, len(examples) - 1)]
    return args


_MAX_EXAMPLES = 4


async def _probe(tool: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (args, default payload) for a call built from the tool's own examples.

    Each example index is tried in turn. The fixture database is a deliberately tiny
    slice of Orphanet, so a tool's FIRST (most illustrative) example may legitimately
    name a disorder these fixtures do not carry — trying the others keeps the arguments
    schema-derived rather than hardcoded, while still landing on a record the fixture
    can serve. If no example resolves at all, the tool's advertised examples are wrong:
    that is a failure, not a skip (the live behaviour gate makes the same demand of the
    real corpus — "its own documented example is callable").
    """
    args = _example_args(tool)
    assert args is not None, f"{tool.name}: unprobeable — a required parameter has no `examples`"
    attempts: list[dict[str, Any]] = []
    first_ok: tuple[dict[str, Any], dict[str, Any]] | None = None
    for index in range(_MAX_EXAMPLES):
        candidate = _example_args(tool, index)
        if candidate is None or candidate in attempts:
            break
        attempts.append(candidate)
        payload = envelope(await tool.fn(**candidate))
        if payload.get("success") is not True:
            continue
        # Prefer an example that actually returns records: a call that legitimately
        # yields nothing satisfies every assertion below VACUOUSLY (0 == 0), which is
        # how a payload-destroying bug hides from its own regression test.
        if any(records for records in _collections(payload).values()):
            return candidate, payload
        first_ok = first_ok or (candidate, payload)
    if first_ok is not None:
        return first_ok
    raise AssertionError(
        f"{tool.name}: none of its advertised examples resolved against the fixture corpus "
        f"({attempts}) — the tool's `examples` do not describe a callable call."
    )


def _accepts_response_mode(tool: Any) -> bool:
    props = dict(getattr(tool, "parameters", None) or {}).get("properties") or {}
    return "response_mode" in props


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_every_tool_is_probeable_from_its_own_examples(
    facade: FastMCP, tool_name: str
) -> None:
    """S2/S3: every required parameter carries an example, so no tool ships UNGATED."""
    tool = await _tool(facade, tool_name)
    assert _example_args(tool) is not None, (
        f"{tool_name}: a required parameter carries no `examples`, so neither this test "
        "nor the fleet behaviour gate can construct a valid call. The tool ships UNGATED "
        "(TOOL-SCHEMA-DOCUMENTATION-STANDARD S2)."
    )


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
@pytest.mark.parametrize("mode", RESPONSE_MODES)
async def test_response_mode_preserves_every_record(
    facade: FastMCP, tool_name: str, mode: str
) -> None:
    """No response_mode may drop a record from any collection the default call returns."""
    tool = await _tool(facade, tool_name)
    if not _accepts_response_mode(tool):
        pytest.skip(f"{tool_name} takes no response_mode")

    args, default = await _probe(tool)
    shaped = envelope(await tool.fn(**args, response_mode=mode))
    assert shaped.get("success") is True, f"{tool_name}: response_mode={mode!r} failed: {shaped}"

    baseline = _collections(default)
    narrowed = _collections(shaped)

    for key, records in baseline.items():
        assert key in narrowed, (
            f"{tool_name}: response_mode={mode!r} DELETED the {key!r} collection "
            f"({len(records)} records in the default call) and still reported success:true. "
            "minimal narrows a record; it never deletes a collection "
            "(RESPONSE-ENVELOPE-STANDARD-v1)."
        )
        assert len(narrowed[key]) == len(records), (
            f"{tool_name}: response_mode={mode!r} returned {len(narrowed[key])} {key!r} "
            f"records; the default call returned {len(records)}. A mode may return fewer "
            "FIELDS per record, never fewer RECORDS."
        )
        if mode != "minimal":
            # standard/full are legitimately RICHER than the compact default (compact
            # drops nulls that they keep), so only the count invariant binds them. The
            # field-narrowing direction is asserted where it is claimed: minimal.
            continue
        for before, after in zip(records, narrowed[key], strict=True):
            assert _fields(after) <= _fields(before), (
                f"{tool_name}: response_mode='minimal' returned MORE fields on a {key!r} "
                f"record than the default: {sorted(_fields(after) - _fields(before))}"
            )
            if _fields(before):
                assert _fields(after), (
                    f"{tool_name}: response_mode='minimal' emptied a {key!r} record to {{}}. "
                    "The record survives but carries no identifier — declare its stable "
                    "identifier fields in shaping._ROW_IDENTIFIERS."
                )


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_minimal_keeps_the_zero_versus_n_signal(facade: FastMCP, tool_name: str) -> None:
    """The count/total a caller reads to tell "none exist" from "none were sent" survives.

    The audit's core finding: with ``count`` dropped, an empty payload and a discarded
    payload are byte-identical to the caller.
    """
    tool = await _tool(facade, tool_name)
    if not _accepts_response_mode(tool):
        pytest.skip(f"{tool_name} takes no response_mode")

    args, default = await _probe(tool)
    minimal = envelope(await tool.fn(**args, response_mode="minimal"))
    for key in ("count", "total"):
        if key in default:
            assert minimal.get(key) == default[key], (
                f"{tool_name}: response_mode='minimal' dropped or changed {key!r} "
                f"({default[key]!r} -> {minimal.get(key)!r}). It is the only signal that "
                "distinguishes an empty result from a discarded payload."
            )


async def test_the_probe_is_not_vacuous(facade: FastMCP) -> None:
    """Guard the guard: the fixture corpus must actually exercise non-empty collections.

    Every assertion above is trivially true for a tool whose collections are empty. If
    the fixture database ever stops carrying rows for these tools, the suite would keep
    reporting green while proving nothing — so pin the floor explicitly.
    """
    exercised: dict[str, int] = {}
    for name in TOOL_NAMES:
        tool = await _tool(facade, name)
        if not _accepts_response_mode(tool):
            continue
        _, default = await _probe(tool)
        for key, records in _collections(default).items():
            if records:
                exercised[f"{name}.{key}"] = len(records)

    assert len(exercised) >= 8, (
        "the fixture corpus no longer exercises enough non-empty collections for the "
        f"response_mode contract to mean anything: only {sorted(exercised)}"
    )
