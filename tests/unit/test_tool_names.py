"""Tool registration coverage and Tool-Naming Standard compliance.

The six ``register_*`` functions together must register EXACTLY the frozen
TOOLS set, and every name must be unprefixed snake_case starting with a canonical
verb so it composes cleanly behind a namespacing gateway.
"""

from __future__ import annotations

import re

import pytest

from orphanet_link.mcp.capabilities import TOOLS
from orphanet_link.mcp.facade import create_orphanet_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
_CANONICAL_VERBS = frozenset(
    {
        "get",
        "search",
        "list",
        "resolve",
        "find",
        "compare",
        "compute",
        "predict",
        "analyze",
        "annotate",
        "submit",
        "export",
        "generate",
        "download",
        "map",
    }
)
_NAMESPACE = "orphanet"


def _assert_standard_tool_name(name: str) -> None:
    """Assert a local tool name mirrors the router strict-naming contract."""
    assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
    leading_verb = name.split("_", 1)[0]
    assert leading_verb in _CANONICAL_VERBS, (
        f"{name!r} must start with a canonical verb from {sorted(_CANONICAL_VERBS)}"
    )
    assert not name.startswith(f"{_NAMESPACE}_"), (
        f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace token"
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


async def test_tool_names_conform_to_standard() -> None:
    """Every tool name must match the naming convention."""
    mcp = create_orphanet_mcp()
    names = sorted(t.name for t in await mcp.list_tools())
    assert names, "no tools registered"
    for name in names:
        _assert_standard_tool_name(name)


def test_tool_name_standard_accepts_map_and_rejects_unknown_verbs() -> None:
    """The local mirror allows router-accepted ``map`` but rejects unknown verbs."""
    _assert_standard_tool_name("map_cross_ontology")

    with pytest.raises(AssertionError, match="must start with a canonical verb"):
        _assert_standard_tool_name("inspect_disease")


async def test_tool_count_matches_declared() -> None:
    """The facade must expose exactly 19 tools (all domain tools + 2 discovery tools)."""
    mcp = create_orphanet_mcp()
    registered = await mcp.list_tools()
    assert len(registered) == len(TOOLS), (
        f"Expected {len(TOOLS)} tools, got {len(registered)}: {sorted(t.name for t in registered)}"
    )
