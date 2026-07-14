"""Read the envelope out of a tool result, whichever shape carries it.

The SUCCESS path returns a plain dict (FastMCP serialises it into
``structuredContent``). The ERROR path returns a ``ToolResult`` so the same envelope
can ALSO carry MCP's ``isError: true`` -- a returned dict can never set the protocol
flag, so a client branching on ``isError``, exactly as the protocol tells it to, read
every one of this server's error envelopes as a successful call.

Tests assert on the envelope itself, so they unwrap through here.
"""

from __future__ import annotations

from typing import Any

from fastmcp.tools.tool import ToolResult


def envelope(result: Any) -> dict[str, Any]:
    """The envelope dict, unwrapped from a ``ToolResult`` when the tool errored."""
    if isinstance(result, ToolResult):
        assert isinstance(result.structured_content, dict), (
            "an error ToolResult must still carry the machine-readable envelope in "
            "structured_content -- raising would have discarded it"
        )
        return result.structured_content
    assert isinstance(result, dict)
    return result


def raised_is_error(result: Any) -> bool:
    """True when the result carries MCP's ``isError: true`` (Response-Envelope v1)."""
    return isinstance(result, ToolResult) and result.is_error is True
