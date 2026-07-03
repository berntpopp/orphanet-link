"""Shared harness + fixture constants for the snapshot characterization tests.

Not a test module (leading underscore -> not collected). Holds the volatile-field
normalizer and the small projection/assert helpers used by ``test_snapshots*.py``
so each test file stays within the 500-line budget.
"""

from __future__ import annotations

from typing import Any, cast

from fastmcp import FastMCP

_ORPHA_166024 = "ORPHA:166024"  # gene KIF7; xref OMIM:607131; parent 93419 (-> 156)
_ORPHA_58 = "ORPHA:58"  # Alexander disease; phenotype HP:0000256

#: Canonical names for the two fixture disorders (reused across snapshots).
_NAME_166024 = "Multiple epiphyseal dysplasia-macrocephaly-facial dysmorphism syndrome"
_NAME_58 = "Alexander disease"
#: Exact-match OMIM 607131 xref row, as it appears in get_disease/map_cross_ontology.
_OMIM_607131 = {"object_id": "607131", "mapping_relation": "E", "validation_status": "Validated"}

#: _meta keys that vary per call or per release and must be dropped before compare.
_VOLATILE_META = {"request_id", "elapsed_ms", "data_version", "capabilities_version"}


def _normalize(obj: Any) -> Any:
    """Strip volatile fields recursively so snapshots are stable across releases.

    Drops the release-dependent top-level ``orphanet_version`` and the volatile
    ``_meta`` sub-keys (request_id, elapsed_ms, data_version, capabilities_version);
    keeps every other key and value.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "orphanet_version":
                continue
            if key == "_meta" and isinstance(value, dict):
                value = {k: v for k, v in value.items() if k not in _VOLATILE_META}
            out[key] = _normalize(value)
        return out
    if isinstance(obj, list):
        return [_normalize(item) for item in obj]
    return obj


async def _tools(facade: FastMCP) -> dict[str, Any]:
    return {t.name: t for t in await facade.list_tools()}


async def _call(facade: FastMCP, name: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke a tool's callable and return its normalized (volatile-stripped) output."""
    tools = await _tools(facade)
    return cast("dict[str, Any]", _normalize(await tools[name].fn(**kwargs)))


def _subset(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Project ``payload`` down to ``keys`` (for curated stable-subset snapshots)."""
    return {k: payload[k] for k in keys}


def _pick(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Like ``_subset`` but tolerant of absent keys (compact drops null leaves)."""
    return {k: payload[k] for k in keys if k in payload}


def _has_null(obj: Any) -> bool:
    """True if ``None`` appears anywhere in a nested dict/list structure."""
    if obj is None:
        return True
    if isinstance(obj, dict):
        return any(_has_null(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_null(v) for v in obj)
    return False


def _step(tool: str, term: str) -> dict[str, Any]:
    """A single next_commands entry: a follow-on tool keyed by a term argument."""
    return {"tool": tool, "arguments": {"term": term}}


def _meta(tool: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The normalized _meta envelope every compact response carries.

    ``source`` + ``tool`` + ``next_commands`` + the fixed research-use disclaimer
    ``unsafe_for_clinical_use`` (fleet disclaimer standardization; present at every
    response_mode, so it survives ``_normalize``'s volatile-key strip).
    """
    return {
        "source": "orphanet",
        "tool": tool,
        "unsafe_for_clinical_use": True,
        "next_commands": steps,
    }
