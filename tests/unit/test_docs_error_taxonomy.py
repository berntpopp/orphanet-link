"""The documented error taxonomy must match the one the server actually serves.

``ERROR_CODES`` in ``orphanet_link.mcp.capabilities`` is the single source of truth
for the taxonomy. Two *prose* surfaces restate it and can rot silently:

1. ``docs/architecture.md`` (``## Error taxonomy``) — what a client integrator reads.
2. ``ORPHANET_REFERENCE_NOTES`` in ``orphanet_link.mcp.resources`` — the string the
   server itself hands clients over ``orphanet://reference``.

Both were unguarded, and the doc had drifted: it claimed *seven* codes and omitted
``limit_exceeded``, so a client writing error handling from it would have missed a
whole recoverable branch. These tests bind both restatements — the count, the codes,
and the ``recovery_action`` / ``retryable`` routing table — to the code, never to a
second hardcoded copy of the list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from orphanet_link.mcp.capabilities import ERROR_CODES
from orphanet_link.mcp.envelope import _RETRYABLE, _recovery_action
from orphanet_link.mcp.resources import ORPHANET_REFERENCE_NOTES

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = ROOT / "docs" / "architecture.md"

#: Spelled-out counts, so "Eight codes:" is checked and not just the list length.
_NUMBER_WORDS = {
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
}

#: "Eight codes: `invalid_input`, `not_found`, ... `internal_error`."
_DOC_SENTENCE = re.compile(r"(?P<count>[A-Za-z]+) codes: (?P<codes>[^.]+)\.")

#: "Error codes (8): invalid_input, not_found, ... internal_error."
_NOTES_SENTENCE = re.compile(r"Error codes \((?P<count>\d+)\): (?P<codes>[^.]+)\.")

#: A row of the recovery table: | `action` | `true` | `code`, `code` |
_TABLE_ROW = re.compile(
    r"^\|\s*`(?P<action>\w+)`\s*\|\s*`(?P<retryable>true|false)`\s*\|(?P<codes>[^|]+)\|"
)


def _taxonomy_section() -> str:
    """Return the body of the ``## Error taxonomy`` section of architecture.md."""
    section: list[str] = []
    inside = False

    for line in ARCHITECTURE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Error taxonomy"
            continue
        if inside:
            section.append(line)

    assert section, "no '## Error taxonomy' section found in docs/architecture.md"
    return "\n".join(section)


def test_architecture_doc_lists_every_error_code_and_states_the_right_count() -> None:
    """docs/architecture.md must name exactly the codes the server declares."""
    section = " ".join(_taxonomy_section().split())

    match = _DOC_SENTENCE.search(section)
    assert match, "the '## Error taxonomy' section must open with '<N> codes: `a`, `b`, ...'"

    documented = re.findall(r"`([a-z_]+)`", match.group("codes"))
    assert documented == ERROR_CODES, (
        "docs/architecture.md is out of sync with capabilities.ERROR_CODES.\n"
        f"Declared but undocumented: {sorted(set(ERROR_CODES) - set(documented))}\n"
        f"Documented but not declared: {sorted(set(documented) - set(ERROR_CODES))}"
    )

    expected_count = _NUMBER_WORDS[len(ERROR_CODES)]
    assert match.group("count") == expected_count, (
        f"docs/architecture.md says '{match.group('count')} codes' but the server "
        f"declares {len(ERROR_CODES)} ({expected_count})."
    )


def test_architecture_doc_recovery_table_matches_the_envelope_routing() -> None:
    """The documented recovery_action / retryable table must match ``envelope``."""
    rows = [
        match
        for line in _taxonomy_section().splitlines()
        if (match := _TABLE_ROW.match(line.strip()))
    ]
    assert rows, "no recovery_action rows found in the '## Error taxonomy' table"

    covered: list[str] = []
    for row in rows:
        action = row.group("action")
        retryable = row.group("retryable") == "true"

        for code in re.findall(r"`([a-z_]+)`", row.group("codes")):
            covered.append(code)
            assert _recovery_action(code) == action, (
                f"docs/architecture.md routes {code!r} to {action!r}, but the envelope "
                f"routes it to {_recovery_action(code)!r}."
            )
            assert (code in _RETRYABLE) is retryable, (
                f"docs/architecture.md marks {code!r} retryable={retryable}, but the "
                f"envelope says {code in _RETRYABLE}."
            )

    assert sorted(covered) == sorted(ERROR_CODES), (
        "the recovery table must route every declared error code exactly once.\n"
        f"Missing: {sorted(set(ERROR_CODES) - set(covered))}\n"
        f"Unknown: {sorted(set(covered) - set(ERROR_CODES))}"
    )


def test_reference_resource_notes_list_every_error_code() -> None:
    """``orphanet://reference`` restates the taxonomy to clients — bind it too."""
    match = _NOTES_SENTENCE.search(ORPHANET_REFERENCE_NOTES)
    assert match, "ORPHANET_REFERENCE_NOTES must state 'Error codes (N): ...'"

    served = [code.strip() for code in match.group("codes").split(",")]
    assert served == ERROR_CODES
    assert int(match.group("count")) == len(ERROR_CODES)


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_declared_code_has_a_recovery_action(code: str) -> None:
    """No declared code may fall through to an undocumented recovery branch."""
    assert _recovery_action(code) in {"retry_backoff", "reformulate_input", "switch_tool"}
