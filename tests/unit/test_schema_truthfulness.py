"""A tool's description MUST NOT promise what its schema does not accept.

The dangerous direction is docs-more-permissive-than-runtime: the model reads the
description, obeys it, and the call HARD-FAILS. `map_cross_ontology`'s description
advertised a `fields=['xrefs.OMIM']` projection. The tool has no `fields` property and
`additionalProperties: false`, so the documented call was rejected outright — and the
key it named (`xrefs`) is not even the key this tool returns (`mappings`). The sentence
was wrong twice.

The parameter check is derived from the registry: every tool's description is scanned
for `name=` promises and each one must exist in that tool's own input schema. No
hardcoded list of tools, no hardcoded list of parameters — a new tool that invents a
parameter in its prose is caught the day it ships.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest
from fastmcp import FastMCP

from orphanet_link.mcp.facade import create_orphanet_mcp
from orphanet_link.mcp.tools._common import MAX_TERM_CHARS
from tests.unit._envelope import envelope

#: A `word=` token in a description reads to a model as "this tool takes this argument".
#: The signature line ("Signature: get_disease(term, response_mode=)") uses the same
#: form, which is exactly why a stale one is so convincing.
_PROMISED_ARG = re.compile(r"\b([a-z_][a-z0-9_]{2,})=")

#: Prose that legitimately contains `word=` without naming a parameter of THIS tool.
_NOT_A_PARAMETER = {"e", "g", "i"}


def _registered_tool_names() -> list[str]:
    mcp = create_orphanet_mcp()
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


TOOL_NAMES = _registered_tool_names()


async def _tool(facade: FastMCP, name: str) -> Any:
    return next(t for t in await facade.list_tools() if t.name == name)


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_description_promises_only_parameters_the_tool_accepts(
    facade: FastMCP, tool_name: str
) -> None:
    """Every `arg=` a description mentions must be a real property of that tool."""
    tool = await _tool(facade, tool_name)
    schema = dict(getattr(tool, "parameters", None) or {})
    accepted = set(schema.get("properties") or {})
    promised = {
        name
        for name in _PROMISED_ARG.findall(tool.description or "")
        if name not in _NOT_A_PARAMETER
    }
    invented = promised - accepted
    assert not invented, (
        f"{tool_name}: its description promises {sorted(invented)}, which its input schema "
        f"does not accept (it accepts {sorted(accepted)}). additionalProperties is false, so "
        "a model that follows the description gets a hard invalid_input. Delete the promise "
        "or implement the parameter."
    )


async def test_map_cross_ontology_names_the_key_it_actually_returns(facade: FastMCP) -> None:
    """It returns `mappings`; its description must not point the model at `xrefs`."""
    tool = await _tool(facade, "map_cross_ontology")
    payload = envelope(await tool.fn(term="ORPHA:166024"))
    assert "mappings" in payload
    assert "mappings" in (tool.description or ""), (
        "the description must name the key this tool actually returns"
    )


async def test_an_over_long_query_is_rejected_not_amplified(facade: FastMCP) -> None:
    """An unbounded free-text arg is echoed twice; bound it in the schema (S5).

    A 5,000-character query used to return HTTP 200, zero results, and a ~10,400-character
    response: the junk echoed back in `query` AND again in `_meta.next_commands`. The
    caller paid ~2x its own garbage for zero information.
    """
    tool = await _tool(facade, "search_diseases")
    schema = dict(getattr(tool, "parameters", None) or {})
    assert schema["properties"]["query"]["maxLength"] == MAX_TERM_CHARS, (
        "the bound must be DECLARED in the schema, so the model can see it and pydantic "
        "can enforce it before the tool body ever runs"
    )


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_every_free_text_string_arg_declares_a_bound(facade: FastMCP, tool_name: str) -> None:
    """No unbounded string parameter anywhere on the surface."""
    tool = await _tool(facade, tool_name)
    schema = dict(getattr(tool, "parameters", None) or {})
    for name, prop in (schema.get("properties") or {}).items():
        branches = [prop, *(b for b in prop.get("anyOf") or [] if isinstance(b, dict))]
        for branch in branches:
            if branch.get("type") != "string" or branch.get("enum"):
                continue
            assert "maxLength" in branch, (
                f"{tool_name}.{name} is an unbounded string. A caller's junk is echoed back "
                "in the payload and again in _meta.next_commands, so it costs ~2x its own "
                "size for zero information. Declare a maxLength (S5)."
            )


# --------------------------------------------------------------------------- array filters

_SENTINEL = "__gf_no_such_value__"


def _array_string_branches(prop: dict[str, Any]) -> list[dict[str, Any]]:
    """The array-of-string branches of a property (through an anyOf nullable wrapper)."""
    out: list[dict[str, Any]] = []
    for branch in [prop, *(b for b in prop.get("anyOf") or [] if isinstance(b, dict))]:
        items = branch.get("items")
        if branch.get("type") == "array" and isinstance(items, dict):
            out.append(branch)
    return out


def _example_args(tool: Any, index: int = 0) -> dict[str, Any] | None:
    schema = dict(getattr(tool, "parameters", None) or {})
    props = schema.get("properties") or {}
    args: dict[str, Any] = {}
    for name in schema.get("required") or []:
        examples = (props.get(name) or {}).get("examples")
        if not examples:
            return None
        args[name] = examples[min(index, len(examples) - 1)]
    return args


async def _resolving_base(tool: Any) -> dict[str, Any] | None:
    """A required-args call built from the tool's examples that RESOLVES in the fixture.

    The tiny fixture database carries only a few disorders, so a tool's first (most
    illustrative) example may name one it does not have. Try each example in turn.
    """
    for index in range(4):
        candidate = _example_args(tool, index)
        if candidate is None:
            return None
        result = envelope(await tool.fn(**candidate))
        if result.get("success") is True:
            return candidate
    return None


def _batch_items(result: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The per-item rows of a partial-success batch envelope, if this is one."""
    results = result.get("results")
    if (
        isinstance(results, list)
        and results
        and all(isinstance(r, dict) and "ok" in r for r in results)
    ):
        return results
    return None


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_optional_array_filters_reject_an_unrecognised_value(
    facade: FastMCP, tool_name: str
) -> None:
    """Every OPTIONAL array-of-string filter is a closed vocabulary — and must act like one.

    This is the array analogue of the fleet gate's silent-empty check, and it is the
    finding that reopened this review: ``map_cross_ontology.prefixes`` shipped as a bare
    ``list[str]`` and ``prefixes=["__bogus__"]`` returned ``count: 0, success: true`` --
    indistinguishable from a disorder with no such cross-references. The old gate could
    not see it (it probed only SCALAR filters, and its row-finder ignored the grouped
    ``mappings`` object). ``get_disease.include`` and ``get_disease.fields`` are the same
    shape.

    A REQUIRED array (``queries``/``terms``) is the primary INPUT, not a filter: a bogus
    item there is legitimately answered with a per-item failure inside a successful batch,
    so only optional filters are probed -- exactly as the gate scopes it.

    The cure is either shape: declare an item ``enum`` (pydantic then rejects at binding)
    or validate at runtime. Both surface as an ``invalid_input`` envelope, which is what
    this asserts -- a zero-row ``success: true`` is the failure.
    """
    tool = await _tool(facade, tool_name)
    schema = dict(getattr(tool, "parameters", None) or {})
    required = set(schema.get("required") or [])

    candidates = [
        name
        for name, prop in (schema.get("properties") or {}).items()
        if name not in required
        and _array_string_branches(prop)
        and _array_string_branches(prop)[0]["items"].get("type") in ("string", None)
    ]
    if not candidates:
        pytest.skip(f"{tool_name}: no optional array-of-string filter")

    base = await _resolving_base(tool)
    if base is None:
        pytest.skip(f"{tool_name}: no example resolves against the fixture corpus")

    for name in candidates:
        result = envelope(await tool.fn(**{**base, name: [_SENTINEL]}))
        items = _batch_items(result)
        if items is not None:
            # A partial-success batch surfaces the bad filter PER ITEM (the envelope stays
            # success:true, exactly like the isError contract). Every item must carry the
            # rejection -- none may silently succeed with the filter ignored.
            assert all(row.get("ok") is False for row in items), (
                f"{tool_name}.{name}: a bogus filter left some batch items succeeding: {items}"
            )
            assert all(row.get("error_code") == "invalid_input" for row in items), (
                f"{tool_name}.{name}: batch items rejected with the wrong code: {items}"
            )
            continue
        assert result.get("success") is False, (
            f"{tool_name}.{name}: an unrecognised array value returned "
            f"success={result.get('success')!r} (count={result.get('count')!r}) instead of an "
            "error. A closed array vocabulary must declare an item enum or reject the value -- "
            "a zero-row success is the silent-empty bug."
        )
        assert result.get("error_code") == "invalid_input", (
            f"{tool_name}.{name}: rejected with {result.get('error_code')!r}, expected invalid_input"
        )


# ---------------------------------------------------------------- the DISCOVERY payload lies too


async def test_capabilities_payload_does_not_promise_the_rejected_parameter(
    facade: FastMCP,
) -> None:
    """A model following the recommended discovery workflow must not be misled either.

    The decorator description is not the only surface a model reads: ``get_server_capabilities``
    and ``orphanet://capabilities`` restate the contract, and THOSE still told a model that
    ``map_cross_ontology`` accepts ``fields=[...]`` -- which it rejects. The whole serialised
    discovery payload (prose + per-tool signatures) is checked, not just the decorator string.
    """
    from orphanet_link.mcp.capabilities import build_capabilities, collect_tool_signatures

    payload = build_capabilities()
    payload["tool_signatures"] = await collect_tool_signatures(facade)
    blob = json.dumps(payload)

    # map_cross_ontology's real signature has no `fields` argument.
    sig = payload["tool_signatures"]["map_cross_ontology"]
    assert "fields=" not in sig, f"the advertised signature still promises fields: {sig!r}"

    # And no prose may pair map_cross_ontology with a fields= projection.
    assert "map_cross_ontology accept fields" not in blob
    assert "map_cross_ontology accepts fields" not in blob


async def test_capabilities_payload_describes_minimal_truthfully(facade: FastMCP) -> None:
    """The discovery prose must not still say minimal 'keeps only orpha_code + name'.

    That directly contradicts this PR's central fix (minimal keeps every collection,
    narrowed to identifiers). A model reading it would never send response_mode=minimal to
    a collection tool expecting rows back.
    """
    from orphanet_link.mcp.capabilities import build_capabilities

    blob = json.dumps(build_capabilities())
    assert "minimal keeps only orpha_code" not in blob, (
        "the response_mode prose still claims minimal drops collections"
    )
