"""Contract: ``error_code`` is a CLOSED enum, and nothing can leak outside it.

Response-Envelope Standard v1 fixes the taxonomy at exactly six codes. orphanet-link
shipped three of its own invention — ``data_unavailable``, ``limit_exceeded`` and
``internal_error`` — so a client written against the fleet contract had no branch for
any of them, and the fleet behaviour gate rejected every error frame this server
produced.

The guard is derived, not hardcoded twice:

* :data:`RATIFIED` is the standard's enum, written out ONCE here — this is the
  external contract, so it is deliberately spelled in full rather than imported from
  the code it is meant to police. (A test that imports the value it checks proves
  nothing.)
* every exception type the package defines is discovered by walking
  ``orphanet_link.exceptions`` — a NEW exception class is therefore gated the moment
  it is added, without anyone remembering to list it here. That is the failure this
  repo has already made once at one level up.
"""

from __future__ import annotations

import inspect

import pytest

from orphanet_link import exceptions as exc_module
from orphanet_link.mcp.capabilities import ERROR_CODES
from orphanet_link.mcp.envelope import McpToolError, _classify, _recovery_action

#: Response-Envelope Standard v1, verbatim. Exactly these six, and nothing else.
RATIFIED = frozenset(
    {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    }
)


def _exception_types() -> list[type[BaseException]]:
    """Every OrphanetError subclass the package defines, discovered by reflection."""
    return [
        obj
        for _, obj in inspect.getmembers(exc_module, inspect.isclass)
        if issubclass(obj, exc_module.OrphanetError) and obj is not exc_module.OrphanetError
    ]


def test_served_error_codes_are_exactly_the_ratified_enum() -> None:
    """What get_server_capabilities and orphanet://reference advertise."""
    assert set(ERROR_CODES) == RATIFIED
    assert len(ERROR_CODES) == len(RATIFIED), "no duplicates"


def _instantiate(exc_type: type[BaseException]) -> BaseException:
    """Build an instance of any exception type, filling required kwargs from its signature.

    Reflection over the constructor, so a new exception with new required arguments is
    still exercised rather than quietly skipped.
    """
    signature = inspect.signature(exc_type)
    kwargs: dict[str, object] = {}
    positional: list[object] = []
    for name, param in signature.parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        value: object = [] if "replaced_by" in name else "boom"
        if param.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[name] = value
        else:
            positional.append(value)
    return exc_type(*positional, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("exc_type", _exception_types(), ids=lambda t: t.__name__)
def test_every_exception_classifies_into_the_closed_enum(exc_type: type[BaseException]) -> None:
    """No typed failure — present or future — may produce a code outside the enum."""
    exc = _instantiate(exc_type)
    code, message = _classify(exc)
    assert code in RATIFIED, (
        f"{exc_type.__name__} classifies to {code!r}, which is not in the closed enum "
        f"{sorted(RATIFIED)}. A client written against the fleet contract has no branch "
        "for it. Fold it onto the canon in envelope._classify."
    )
    assert message, "every error frame must carry a client-safe message"


def test_an_untyped_exception_classifies_to_internal() -> None:
    code, _ = _classify(ValueError("boom"))
    assert code == "internal"


@pytest.mark.parametrize("code", sorted(RATIFIED))
def test_every_code_routes_to_a_recovery_action(code: str) -> None:
    """Each code tells the model what to DO next, not merely what went wrong."""
    assert _recovery_action(code) in {"retry_backoff", "reformulate_input", "switch_tool"}


def test_not_found_is_not_used_for_a_bad_argument() -> None:
    """`not_found` means "the thing does not exist" — never "your argument was wrong".

    Answering a bad argument with not_found tells the model the TOOL does not exist, so
    it strikes it from its list and never calls it again.
    """
    code, _ = _classify(exc_module.InvalidInputError("bad", field="term"))
    assert code == "invalid_input"


def test_mctoolerror_passes_a_valid_code_through() -> None:
    """An in-enum code raised via McpToolError reaches the envelope unchanged."""
    code, message = _classify(McpToolError(error_code="not_found", message="gone"))
    assert code == "not_found"
    assert message == "gone"


def test_mctoolerror_with_an_off_contract_code_is_severed_to_internal() -> None:
    """The ONE branch that echoes its code verbatim must still not escape the enum.

    ``McpToolError.error_code`` is typed ``ErrorCode``, but a type annotation is not
    enforced by the interpreter -- and this is the only ``_classify`` branch that does not
    hardcode its code. Codex reproduced an ``isError: true`` envelope carrying
    ``error_code: "outside_contract"`` through exactly this path. ``_classify`` now
    re-checks it at runtime and severs anything outside the enum to ``internal``. The
    reflection sweep above never sees this path (it only discovers ``OrphanetError``
    subclasses), so it is pinned explicitly here.
    """
    # Bypass the typed constructor the way an untyped runtime / a mis-cast would.
    rogue = McpToolError(error_code="not_found", message="hostile")
    rogue.error_code = "outside_contract"  # type: ignore[assignment]
    code, message = _classify(rogue)
    assert code == "internal", f"an off-contract code escaped as {code!r}"
    assert code in RATIFIED
    # The message survives (it is server-authored and sanitized elsewhere); only the
    # code is severed.
    assert message == "hostile"
