"""Every declared error code has a triggering test (assessment P6.1).

``run_mcp_tool`` is the MCP error boundary: tools return a plain dict and it
injects ``success``/``_meta`` on success or converts any exception into a
structured error dict (returned, never raised). These tests drive each documented
error code by passing a ``call`` that raises the matching typed exception and pin
the resulting envelope shape -- ``error_code``, ``retryable``, ``recovery_action``,
the structured top-level keys, and the lean ``_meta`` core ``{tool, request_id,
source}`` -- so a future change to the taxonomy cannot silently drift.

The error envelope is built by ``run_mcp_tool(name, call, context=...)`` where
``call`` is an ``async`` zero-arg function returning a dict (or raising).
"""

from __future__ import annotations

from typing import Any

import pytest

from orphanet_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)
from orphanet_link.mcp.envelope import McpErrorContext, run_mcp_tool
from orphanet_link.mcp.untrusted_content import UntrustedTextLimitError
from orphanet_link.services.orphanet_service import OrphanetService
from tests.unit._envelope import envelope


def _raiser(exc: BaseException):
    """Return an async zero-arg ``call`` that raises ``exc`` when awaited."""

    async def call() -> dict[str, Any]:
        raise exc

    return call


# Each row: (exception instance, error_code, retryable, recovery_action).
_CASES: list[tuple[BaseException, str, bool, str]] = [
    (InvalidInputError("bad", field="x"), "invalid_input", False, "reformulate_input"),
    (NotFoundError("nope"), "not_found", False, "reformulate_input"),
    (
        AmbiguousQueryError("amb", candidates=[{"orpha_code": "58", "name": "A"}]),
        "ambiguous_query",
        False,
        "reformulate_input",
    ),
    (DataUnavailableError(), "data_unavailable", True, "retry_backoff"),
    (RateLimitError(), "rate_limited", True, "retry_backoff"),
    (ServiceUnavailableError(), "upstream_unavailable", True, "retry_backoff"),
    (DownloadError(), "upstream_unavailable", True, "retry_backoff"),
    # A v1.1 fenced-response ceiling breach is an explicit typed limit error,
    # recoverable by narrowing the request -- never a generic internal_error.
    (
        UntrustedTextLimitError("untrusted object count 300 exceeds ceiling 128"),
        "limit_exceeded",
        False,
        "reformulate_input",
    ),
    (ValueError("boom"), "internal_error", False, "switch_tool"),
]


@pytest.mark.parametrize(("exc", "error_code", "retryable", "recovery_action"), _CASES)
async def test_error_taxonomy_envelope_shape(
    exc: BaseException, error_code: str, retryable: bool, recovery_action: str
) -> None:
    """Each typed exception maps to its documented envelope contract."""
    result = envelope(
        await run_mcp_tool("some_tool", _raiser(exc), context=McpErrorContext("some_tool"))
    )

    assert result["success"] is False
    assert result["error_code"] == error_code
    assert result["retryable"] is retryable
    assert result["recovery_action"] == recovery_action

    meta = result["_meta"]
    assert meta["tool"] == "some_tool"
    assert "request_id" in meta
    assert meta["source"] == "orphanet"


async def test_rate_limited_message_is_fixed() -> None:
    """``rate_limited`` uses the fixed client-safe message, not the raw exception text."""
    result = envelope(
        await run_mcp_tool(
            "t", _raiser(RateLimitError("internal detail")), context=McpErrorContext("t")
        )
    )
    assert result["error_code"] == "rate_limited"
    assert result["message"] == "Upstream rate limit hit. Retry shortly."


async def test_service_unavailable_message_is_fixed() -> None:
    """``upstream_unavailable`` uses the fixed client-safe message."""
    result = envelope(
        await run_mcp_tool(
            "t", _raiser(ServiceUnavailableError("internal detail")), context=McpErrorContext("t")
        )
    )
    assert result["error_code"] == "upstream_unavailable"
    assert result["message"] == "The upstream is temporarily unavailable."


async def test_download_error_maps_to_upstream_unavailable() -> None:
    """``DownloadError`` classifies as ``upstream_unavailable`` with the same message."""
    result = envelope(
        await run_mcp_tool("t", _raiser(DownloadError()), context=McpErrorContext("t"))
    )
    assert result["error_code"] == "upstream_unavailable"
    assert result["message"] == "The upstream is temporarily unavailable."


async def test_invalid_input_surfaces_field() -> None:
    """``invalid_input`` surfaces the offending ``field`` as a top-level key."""
    result = envelope(
        await run_mcp_tool(
            "t", _raiser(InvalidInputError("bad", field="x")), context=McpErrorContext("t")
        )
    )
    assert result["error_code"] == "invalid_input"
    assert result["field"] == "x"


async def test_ambiguous_query_surfaces_candidates_and_next_commands() -> None:
    """``ambiguous_query`` surfaces candidates and chains via non-empty ``next_commands``."""
    result = envelope(
        await run_mcp_tool(
            "t",
            _raiser(AmbiguousQueryError("amb", candidates=[{"orpha_code": "58", "name": "A"}])),
            context=McpErrorContext("t"),
        )
    )
    assert result["error_code"] == "ambiguous_query"
    assert result["candidates"] == [{"orpha_code": "58", "name": "A"}]
    assert result["_meta"]["next_commands"]


async def test_internal_error_does_not_leak_raw_message() -> None:
    """An unexpected exception is masked: the generic message, never the raw ``boom``."""
    result = envelope(
        await run_mcp_tool("t", _raiser(ValueError("boom")), context=McpErrorContext("t"))
    )
    assert result["error_code"] == "internal_error"
    assert result["message"] == "An internal error occurred. The request was not completed."
    assert "boom" not in result["message"]


async def test_data_unavailable_surfaces_through_tool_body() -> None:
    """``data_unavailable`` surfaces end-to-end through a real tool body when unbuilt.

    A fresh ``OrphanetService`` with no repo and no db_path raises
    ``DataUnavailableError`` the moment ``.repo`` is touched. Crucially this does NOT
    touch the global service singleton the session ``facade`` depends on.
    """

    async def call() -> dict[str, Any]:
        return OrphanetService().get_disease("ORPHA:1")

    result = envelope(
        await run_mcp_tool("get_disease", call, context=McpErrorContext("get_disease"))
    )
    assert result["success"] is False
    assert result["error_code"] == "data_unavailable"
    assert result["retryable"] is True
    assert result["recovery_action"] == "retry_backoff"
