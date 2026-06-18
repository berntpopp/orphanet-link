"""Tests for the response-mode projection (services/shaping.py)."""

from __future__ import annotations

from orphanet_link.services.shaping import RESPONSE_MODES, shape

# -- sample record ------------------------------------------------------------

_SAMPLE = {
    "orpha_code": "166024",
    "name": "Acrocallosal syndrome",
    "orphanet_version": "1.3.42",
    "disorder_type": "Disease",
    "definition": "A rare primary bone dysplasia.",
    "synonyms": ["ACS", "Schinzel syndrome"],
    "xrefs": {"OMIM": [{"object_id": "607131"}]},
    "genes": [],
    "some_null": None,
    "some_empty": [],
    "some_blank": "",
}

_ANCHORS = ("orpha_code", "name", "orphanet_version")


# -- RESPONSE_MODES list -------------------------------------------------------


def test_response_modes_contains_expected():
    assert set(RESPONSE_MODES) == {"minimal", "compact", "standard", "full"}


# -- minimal mode --------------------------------------------------------------


def test_minimal_keeps_only_anchors():
    result = shape(_SAMPLE, "minimal", anchors=_ANCHORS)
    assert set(result.keys()) == {"orpha_code", "name", "orphanet_version"}


def test_minimal_does_not_include_extra_fields():
    result = shape(_SAMPLE, "minimal", anchors=_ANCHORS)
    assert "definition" not in result
    assert "synonyms" not in result
    assert "xrefs" not in result


def test_minimal_preserves_meta_keys():
    record = {**_SAMPLE, "_meta": {"tool": "test"}, "success": True}
    result = shape(record, "minimal", anchors=_ANCHORS)
    assert "_meta" in result
    assert "success" in result


# -- compact mode --------------------------------------------------------------


def test_compact_drops_none():
    result = shape(_SAMPLE, "compact")
    assert "some_null" not in result


def test_compact_drops_empty_list():
    result = shape(_SAMPLE, "compact")
    assert "some_empty" not in result


def test_compact_drops_empty_string():
    result = shape(_SAMPLE, "compact")
    assert "some_blank" not in result


def test_compact_retains_non_empty_values():
    result = shape(_SAMPLE, "compact")
    assert result["orpha_code"] == "166024"
    assert result["definition"] == "A rare primary bone dysplasia."
    assert result["synonyms"] == ["ACS", "Schinzel syndrome"]


def test_compact_preserves_meta_keys():
    record = {**_SAMPLE, "_meta": {"tool": "test"}, "success": False}
    result = shape(record, "compact")
    # success=False is a valid value and should be preserved (it's in _PRESERVE_KEYS)
    assert "success" in result


# -- standard / full mode ------------------------------------------------------


def test_standard_is_identity():
    result = shape(_SAMPLE, "standard")
    assert result == _SAMPLE


def test_full_is_identity():
    result = shape(_SAMPLE, "full")
    assert result == _SAMPLE


def test_standard_includes_empty_values():
    result = shape(_SAMPLE, "standard")
    assert "some_null" in result
    assert result["some_null"] is None
    assert "some_empty" in result
    assert result["some_empty"] == []


# -- fields projection ---------------------------------------------------------


def test_fields_retains_anchors_always():
    result = shape(_SAMPLE, "compact", fields=["definition"], anchors=_ANCHORS)
    assert "orpha_code" in result
    assert "name" in result
    assert "orphanet_version" in result


def test_fields_includes_requested_field():
    result = shape(_SAMPLE, "compact", fields=["definition"], anchors=_ANCHORS)
    assert "definition" in result


def test_fields_excludes_unrequested_fields():
    result = shape(_SAMPLE, "compact", fields=["definition"], anchors=_ANCHORS)
    assert "disorder_type" not in result
    assert "synonyms" not in result


def test_fields_nested_dot_notation():
    result = shape(_SAMPLE, "standard", fields=["xrefs.OMIM"], anchors=_ANCHORS)
    assert "xrefs" in result
    assert "OMIM" in result["xrefs"]
    # Should not include other xref groups if they existed
    for key in result["xrefs"]:
        assert key == "OMIM"


def test_fields_none_returns_unchanged():
    result = shape(_SAMPLE, "compact", fields=None)
    # Without fields, just shape by mode
    assert "orpha_code" in result
    assert "some_null" not in result  # compact drops null


def test_fields_empty_list_returns_only_anchors():
    result = shape(_SAMPLE, "compact", fields=[], anchors=_ANCHORS)
    # Empty fields list -> projection keeps only anchors
    assert set(result.keys()) == {"orpha_code", "name", "orphanet_version"}


# -- unknown response_mode falls back to compact -------------------------------


def test_unknown_mode_acts_as_compact():
    result = shape(_SAMPLE, "unknown_mode")
    assert "some_null" not in result
    assert "orpha_code" in result
