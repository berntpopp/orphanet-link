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
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "orphanet_link.ingest.release_assets" in workflow_text
    assert "gh release download" not in workflow_text
    assert "verify_release_identity" in workflow_text
    assert "read_release_identity" in workflow_text
    helper = (ROOT / "orphanet_link/ingest/release_identity.py").read_text()
    assert "schema_version" in helper
    assert "disorder_count" in helper


def test_release_api_ambiguity_fails_closed() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "continue-on-error" not in workflow_text
    assert "|| true" not in workflow_text
    helper = (ROOT / "orphanet_link/ingest/release_assets.py").read_text()
    assert "httpx.codes.NOT_FOUND" in helper
    assert "!= httpx.codes.OK" in helper


def test_identity_states_gate_mutation_without_delete_or_clobber() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "published_noop" in workflow_text
    assert "draft_publish_existing" in workflow_text
    assert "collision" in workflow_text
    assert "gh release delete" not in workflow_text
    assert "--clobber" not in workflow_text
    assert any(
        step.get("if") == "needs.build-and-verify.outputs.state == 'create'"
        for step in _steps(_workflow())
    )


def test_existing_release_retrieval_is_bounded_and_inventory_aware() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "orphanet_link.ingest.release_assets" in workflow_text
    assert "gh release download" not in workflow_text
    assert "MAX_METADATA_BYTES" in (ROOT / "orphanet_link/ingest/release_assets.py").read_text()


def test_build_and_publisher_permissions_are_separated() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert jobs["build-and-verify"]["permissions"] == {"contents": "read"}  # type: ignore[index]
    assert jobs["publish"]["permissions"] == {"contents": "write"}  # type: ignore[index]


def test_create_is_atomic_and_does_not_use_an_overwriting_action() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "softprops/action-gh-release" not in workflow_text
    assert "gh release create" in workflow_text
    assert "--clobber" not in workflow_text


def test_publisher_refetches_and_reverifies_the_draft_immediately_before_publish() -> None:
    """The build-job check cannot authorize a mutable draft minutes later."""
    workflow = _workflow()
    publish_steps = workflow["jobs"]["publish"]["steps"]  # type: ignore[index]
    names = [step.get("name", "") for step in publish_steps]  # type: ignore[union-attr]
    recheck = names.index("Recheck exact draft identity before publication")
    create_draft = names.index("Atomically create a new draft")
    publish = names.index("Publish exact rechecked draft")
    assert create_draft < recheck < publish
    script = publish_steps[recheck]["run"]  # type: ignore[index]
    assert "orphanet_link.ingest.release_assets" in script
    assert "verify_release_identity" in script
    assert "read_release_identity" in script
    assert "draft_publish_existing" in script
    assert "orphanet-release-assets" in str(publish_steps)
