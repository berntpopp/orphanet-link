"""The README '## Tools' table must match the registered tool surface exactly.

The tool table is the first thing a reader trusts and the first thing to rot.
This binds it to the live server: adding, renaming, or removing a tool without
updating the table fails CI. Required by the GeneFoundry README Standard v1.

The tool list is read from the real FastMCP instance (``create_orphanet_mcp``),
the same way ``test_tool_names.py`` does it — never hardcoded here, or the guard
would just be a second copy of the thing it is meant to police.
"""

from __future__ import annotations

import re
from pathlib import Path

from orphanet_link.mcp.facade import create_orphanet_mcp

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

#: A tool row: the first cell is a backticked leaf name.
_TOOL_ROW = re.compile(r"^\|\s*`(?P<name>[a-z0-9_]+)`\s*\|")


def _readme_tool_names() -> set[str]:
    """Extract the tool names listed in the README's ``## Tools`` table."""
    names: set[str] = set()
    in_tools_section = False

    for line in README.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_tools_section = line.strip() == "## Tools"
            continue
        if not in_tools_section:
            continue
        match = _TOOL_ROW.match(line)
        if match:
            names.add(match.group("name"))

    return names


async def test_readme_tool_table_matches_registered_tools() -> None:
    """The README table must list exactly the tools the server registers."""
    documented = _readme_tool_names()
    assert documented, "no tool rows found in the README '## Tools' table"

    mcp = create_orphanet_mcp()
    registered = {tool.name for tool in await mcp.list_tools()}

    assert documented == registered, (
        "README '## Tools' table is out of sync with the registered tools.\n"
        f"Registered but undocumented: {sorted(registered - documented)}\n"
        f"Documented but not registered: {sorted(documented - registered)}"
    )
