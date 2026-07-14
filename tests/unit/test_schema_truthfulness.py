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
