"""Argument-help pure functions — the actionable-error contract.

The MCP spec requires a tool-execution error to carry *"actionable feedback that language
models can use to self-correct."* A closed ARRAY vocabulary (``list[Literal[...]]``, e.g.
``map_cross_ontology.prefixes``) puts its enum under ``items.enum``, one level down from
the parameter. Before this fix ``describe_constraints`` looked only at the top level, so a
bad array ITEM (``prefixes.0``) fell through to the "unknown argument — did you mean
`prefixes`?" name error, which is worse than useless: the argument name IS correct, only
the value is wrong. The model is told to fix the thing that is right.
"""

from __future__ import annotations

from orphanet_link.mcp.arg_help import describe_constraints

# The shape FastMCP emits for `prefixes: list[Literal["OMIM", ...]] | None`.
_LIST_LITERAL_SCHEMA = {
    "anyOf": [
        {"type": "array", "items": {"enum": ["OMIM", "MONDO", "ICD-10"], "type": "string"}},
        {"type": "null"},
    ],
    "default": None,
}

# A plain scalar enum (`response_mode`), for the contrast case.
_SCALAR_ENUM_SCHEMA = {"enum": ["minimal", "compact", "standard", "full"], "type": "string"}


def test_array_item_enum_surfaces_the_allowed_values() -> None:
    result = describe_constraints(_LIST_LITERAL_SCHEMA)
    assert result is not None, "a list[Literal] must yield a constraint, not None"
    allowed, human = result
    assert allowed == ["OMIM", "MONDO", "ICD-10"]
    assert "each item must be one of" in human
    assert "OMIM" in human


def test_scalar_enum_still_surfaces_its_values() -> None:
    allowed, human = describe_constraints(_SCALAR_ENUM_SCHEMA)  # type: ignore[misc]
    assert allowed == ["minimal", "compact", "standard", "full"]
    assert human.startswith("must be one of")


def test_a_free_string_has_no_value_constraint() -> None:
    assert describe_constraints({"type": "string"}) is None


def test_a_free_string_array_has_no_item_enum() -> None:
    """An open array (``list[str]``) must NOT be reported as a closed vocabulary."""
    schema = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    assert describe_constraints(schema) is None
