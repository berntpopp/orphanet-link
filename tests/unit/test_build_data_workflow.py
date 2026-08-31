"""Security contracts for Orphanet data-release identity handling."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict[str, object]:
    value = yaml.safe_load((ROOT / ".github/workflows/build-data.yml").read_text())
    assert isinstance(value, dict)
    return value


def _run_blocks(workflow: dict[str, object]) -> list[str]:
    blocks: list[str] = []
    for job in workflow["jobs"].values():  # type: ignore[union-attr]
        for step in job["steps"]:  # type: ignore[index]
            if "run" in step:  # type: ignore[operator]
                blocks.append(str(step["run"]))  # type: ignore[index]
    return blocks


def _steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for job in workflow["jobs"].values():  # type: ignore[union-attr]
        steps.extend(job["steps"])  # type: ignore[index]
    return steps


def test_existing_release_downloads_exact_assets_and_compares_identity() -> None:
    blocks = _run_blocks(_workflow())
    check = next(block for block in blocks if "releases/tags" in block)
    assert "gh release download" in check
    assert "manifest.json" in check
    assert "orphanet.sqlite.gz.sha256" in check
    assert "verify_release_identity" in check
    assert "read_release_identity" in check
    helper = (ROOT / "orphanet_link/ingest/release_identity.py").read_text()
    assert "schema_version" in helper
    assert "disorder_count" in helper


def test_release_api_ambiguity_fails_closed() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    check = next(block for block in _run_blocks(_workflow()) if "releases/tags" in block)
    assert "continue-on-error" not in workflow_text
    assert "|| true" not in check
    assert "collision" in check
    assert "exit 1" in check


def test_identity_states_gate_mutation_without_delete_or_clobber() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "published_noop" in workflow_text
    assert "draft_publish_existing" in workflow_text
    assert "collision" in workflow_text
    assert "gh release delete" not in workflow_text
    assert "--clobber" not in workflow_text
    assert any(
        step.get("if") == "steps.release_state.outputs.state == 'create'"
        for step in _steps(_workflow())
    )
