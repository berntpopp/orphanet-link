"""Contract tests for the container release trigger and target platform."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from orphanet_link.constants import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "container-release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "container-ci.yml"
MANIFEST = ROOT / "container-release.json"

# genefoundry-router v0.8.6: the first revision whose `ExternalReferenceData` release
# model accepts `data.schema_compatibility` instead of rejecting it as an extra input.
ROUTER_WORKFLOW_SHA = "3d3cc20477828ddbd8a0c980b5b4f709e2612c02"
RUNTIME_CAPABLE_RELEASE_BUILDER = (
    f"berntpopp/genefoundry-router/.github/workflows/_container-release.yml@{ROUTER_WORKFLOW_SHA}"
)
RUNTIME_CAPABLE_CI_BUILDER = (
    f"berntpopp/genefoundry-router/.github/workflows/_container-ci.yml@{ROUTER_WORKFLOW_SHA}"
)


def _load_workflow(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _workflow() -> dict[str, Any]:
    return _load_workflow(WORKFLOW)


def test_container_release_runs_only_for_strict_semver_tags() -> None:
    """A release must require vMAJOR.MINOR.PATCH, not any v-prefixed tag."""
    triggers = _workflow().get("on", _workflow().get(True, {}))
    assert triggers["push"]["tags"] == ["v*.*.*"]


def test_container_release_manifest_declares_linux_amd64_platform() -> None:
    """The release contract must make its single supported image platform explicit."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["platform"] == "linux/amd64"


def test_release_and_ci_workflows_pin_the_same_router_revision() -> None:
    """Both reusable-workflow callers must pin the exact router commit, not just a tag."""
    release_job = _workflow()["jobs"]["container-release"]
    ci_job = _load_workflow(CI_WORKFLOW)["jobs"]["container-ci"]

    assert release_job["uses"] == RUNTIME_CAPABLE_RELEASE_BUILDER
    assert ci_job["uses"] == RUNTIME_CAPABLE_CI_BUILDER


def test_container_release_manifest_declares_the_served_schema_compatibility() -> None:
    """`data.schema_compatibility` must name the version `data_probe` reports."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["data"]["schema_compatibility"] == [str(SCHEMA_VERSION)]


def test_release_gate_rejects_tags_outside_central_stable_semver_contract() -> None:
    """Invalid tag pushes must stop before invoking the reusable release workflow."""
    workflow = _workflow()
    gate = workflow["jobs"]["validate-tag"]
    gate_run = gate["steps"][0]["run"]
    component = r"(?:0|[1-9][0-9]{0,63})"
    stable_ref = re.compile(rf"^refs/tags/v{component}\.{component}\.{component}$")

    for tag in (
        "v1.2",
        "v1.2.3-rc.1",
        "v1.2.3+build",
        "v1.two.3",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        f"v{'1' * 65}.2.3",
    ):
        assert stable_ref.fullmatch(f"refs/tags/{tag}") is None

    for tag in ("v0.0.0", "v1.2.3", f"v{'1' * 64}.2.3"):
        assert stable_ref.fullmatch(f"refs/tags/{tag}") is not None

    assert '"$EVENT_REF"' in gate_run
    assert gate_run.count("(0|[1-9][0-9]{0,63})") == 3
    assert "exit 1" in gate_run
    assert workflow["jobs"]["container-release"]["needs"] == "validate-tag"
