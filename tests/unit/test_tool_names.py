"""Tool registration coverage and Tool-Naming Standard v1.1 compliance.

The register_* functions together must register EXACTLY the frozen TOOLS set,
and every name must be unprefixed snake_case starting with a ratified verb so it
composes cleanly behind a namespacing gateway (mounts under ``orphanet``).

Ratified verb canon (Tool-Naming Standard v1.1, 2026-06-30):
  Tier-1 (universal read/query): get search list resolve find compare compute map
  Tier-2 (domain action/compute): predict annotate recode liftover analyze score
                                   submit export generate download
  ops/meta tag carve-out: tools tagged ``ops`` or ``meta`` skip the verb rule
    (still must match charset/length/no-self-prefix).

Orphanet's current tools use only Tier-1 verbs (get, search, resolve, find, map);
no Tier-2 verbs are in use so the tightened set is the full Tier-1 canon only.
"""

from __future__ import annotations

import re

import pytest

from orphanet_link.mcp.capabilities import TOOLS
from orphanet_link.mcp.facade import create_orphanet_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
# Tier-1: full ratified read/query canon (Standard v1.1)
_TIER1_VERBS = frozenset({"get", "search", "list", "resolve", "find", "compare", "compute", "map"})
# Tier-2: sanctioned domain action/compute verbs — none currently used by orphanet
# (kept for future compliance; added when orphanet ships an action tool)
_TIER2_VERBS: frozenset[str] = frozenset()
_CANONICAL_VERBS = _TIER1_VERBS | _TIER2_VERBS
_NAMESPACE = "orphanet"


def _assert_standard_tool_name(name: str, tags: frozenset[str] = frozenset()) -> None:
    """Assert a local tool name mirrors the router strict-naming contract (v1.1)."""
    assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
    assert not name.startswith(f"{_NAMESPACE}_"), (
        f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace token"
    )
    # ops/meta utilities are exempt from the verb rule (fleet ops carve-out).
    if "ops" in tags or "meta" in tags:
        return
    leading_verb = name.split("_", 1)[0]
    assert leading_verb in _CANONICAL_VERBS, (
        f"{name!r} must start with a canonical verb from {sorted(_CANONICAL_VERBS)}"
    )


async def test_registered_tools_equal_frozen_tools() -> None:
    """The registered tool set must exactly match the declared TOOLS list."""
    mcp = create_orphanet_mcp()
    names = {t.name for t in await mcp.list_tools()}
    assert names == set(TOOLS), (
        f"Registered: {sorted(names)}\nDeclared: {sorted(TOOLS)}\n"
        f"Extra: {sorted(names - set(TOOLS))}\n"
        f"Missing: {sorted(set(TOOLS) - names)}"
    )


async def test_tool_names_conform_to_standard_v1_1() -> None:
    """Every tool name must conform to Tool-Naming Standard v1.1.

    ops/meta-tagged tools skip the verb check but still must satisfy charset,
    length, and no-self-prefix rules.
    """
    mcp = create_orphanet_mcp()
    tools = await mcp.list_tools()
    assert tools, "no tools registered"
    for tool in tools:
        tags = frozenset(tool.tags or ())
        _assert_standard_tool_name(tool.name, tags)


def test_tool_name_standard_accepts_map_and_rejects_unknown_verbs() -> None:
    """Tier-1 allows ``map``; unknown verbs are rejected."""
    _assert_standard_tool_name("map_cross_ontology")

    with pytest.raises(AssertionError, match="must start with a canonical verb"):
        _assert_standard_tool_name("inspect_disease")

    # Former ad-hoc Tier-2 verbs no longer admitted for orphanet
    with pytest.raises(AssertionError, match="must start with a canonical verb"):
        _assert_standard_tool_name("predict_disease")

    with pytest.raises(AssertionError, match="must start with a canonical verb"):
        _assert_standard_tool_name("annotate_disease")


async def test_tool_count_matches_declared() -> None:
    """The facade must expose exactly len(TOOLS) tools."""
    mcp = create_orphanet_mcp()
    registered = await mcp.list_tools()
    assert len(registered) == len(TOOLS), (
        f"Expected {len(TOOLS)} tools, got {len(registered)}: {sorted(t.name for t in registered)}"
    )
