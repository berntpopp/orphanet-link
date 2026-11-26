"""Response-Envelope v1.2: every data tool's result validates against the published schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0
(``envelope-v1.2.schema.json``); its digest is pinned in the sibling ``.sha256`` file.
Each tool is called in-process on the fixture index with the ``examples`` of its own
input schema.

One rule is not met yet and is excluded by name, not by weakening the schema: v1 §1
puts the payload under ``result`` (object) or ``results`` (array), while most tools
here still return their payload flat beside ``success``. Moving it is a breaking
wire change of its own; ``test_payload_sits_under_the_primary_key`` is a strict
xfail that fails the day the payload moves, so this exclusion cannot outlive it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from orphanet_link.mcp.capabilities import TOOLS

_HERE = Path(__file__).parent
_SCHEMA_FILE = _HERE / "envelope-v1.2.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_FILE.read_text(encoding="utf-8")))

_OPS_TOOLS = {"get_server_capabilities", "get_diagnostics"}  # outside the v1.2 rule
_DATA_TOOLS = sorted(set(TOOLS) - _OPS_TOOLS)
_PROVENANCE = ("source", "data_version", "retrieved_at")

#: Parameter values where the schema example is not in the fixture index.
_FIXTURE_ARGS: dict[str, Any] = {"term": "ORPHA:166024", "query": "Alexander disease"}


@pytest.fixture()
def mcp(facade: Any) -> Any:
    """The real server over the fixture index."""
    return facade


async def _call(mcp: Any, name: str, **extra: Any) -> Any:
    schema = next(t for t in await mcp.list_tools() if t.name == name).parameters
    arguments = {
        p: _FIXTURE_ARGS.get(p, schema["properties"][p]["examples"][0])
        for p in schema.get("required", [])
    }
    return await mcp.call_tool(name, {**arguments, **extra})


def _is_payload_key_rule(error: ValidationError) -> bool:
    """The v1 §1 ``result``/``results`` rule at the envelope root (see module docstring)."""
    return error.validator == "anyOf" and not error.absolute_path


def _violations(envelope: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in _VALIDATOR.iter_errors(envelope)
        if not _is_payload_key_rule(e)
    ]


def test_vendored_schema_is_the_pinned_release() -> None:
    pin = (_HERE / "envelope-v1.2.schema.sha256").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(_SCHEMA_FILE.read_bytes()).hexdigest() == pin


@pytest.mark.parametrize("mode", ["minimal", "compact", "full"])
@pytest.mark.parametrize("tool", _DATA_TOOLS)
async def test_data_tool_result_validates(mcp: Any, tool: str, mode: str) -> None:
    result = await _call(mcp, tool, response_mode=mode)
    envelope = result.structured_content
    assert envelope["success"] is True
    assert _violations(envelope) == []
    mirrored = json.loads(result.content[0].text)["_meta"]  # the text block mirrors _meta
    for field in _PROVENANCE:
        assert isinstance(envelope["_meta"][field], str) and envelope["_meta"][field], field
        assert mirrored[field] == envelope["_meta"][field]


async def test_error_results_validate(mcp: Any) -> None:
    calls = [
        ("get_disease", {"term": "ORPHA:999999999"}),  # not_found
        ("get_disease", {"term": "ORPHA:58", "bogus": 1}),  # argument binding
        ("get_disease_genes", {}),  # missing argument
        ("no_such_tool", {}),  # unknown tool
    ]
    for tool, arguments in calls:
        for mode in ("minimal", "compact"):
            if tool != "no_such_tool":
                arguments = {**arguments, "response_mode": mode}
            result = await mcp.call_tool(tool, arguments)
            assert result.structured_content["success"] is False
            assert list(_VALIDATOR.iter_errors(result.structured_content)) == []


@pytest.mark.xfail(strict=True, reason="payload is still flat; v1 §1 result/results is open")
async def test_payload_sits_under_the_primary_key(mcp: Any) -> None:
    _VALIDATOR.validate((await _call(mcp, "get_disease")).structured_content)
