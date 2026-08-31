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
    assert "MAX_METADATA_BYTES" in (ROOT / "orphanet_link/ingest/release_assets.py").read_text()


def test_published_noop_requires_provenance_before_state_output() -> None:
    workflow = _workflow()
    build_steps = workflow["jobs"]["build-and-verify"]["steps"]  # type: ignore[index]
    step = next(
        step for step in build_steps if step.get("name") == "Verify existing release identity"
    )
    script = step["run"]  # type: ignore[index]
    assert "published_noop)" in script
    verify = script.index("gh attestation verify")
    state = script.index('echo "state=$state"', verify)
    assert verify < state
    assert "timeout 120s" in script


def test_every_attestation_check_pins_the_reviewed_workflow_and_source_ref() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    checks = workflow_text.count("gh attestation verify")
    signer = '--signer-workflow "berntpopp/orphanet-link/.github/workflows/build-data.yml"'
    assert checks == 2
    assert workflow_text.count(signer) == checks
    assert workflow_text.count('--source-ref "$GITHUB_REF"') == checks
    # A different workflow identity, including a caller-controlled value, must
    # not be accepted by any of the release attestation checks.
    assert '--signer-workflow "$GITHUB_REPOSITORY' not in workflow_text


def test_build_and_publisher_permissions_are_separated() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert jobs["build-and-verify"]["permissions"] == {"contents": "read"}  # type: ignore[index]
    assert jobs["publish"]["permissions"] == {  # type: ignore[index]
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


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
    create_draft = names.index("Atomically create a new draft")
    publish = names.index("Publish exact rechecked draft")
    assert create_draft < publish
    script = publish_steps[publish]["run"]  # type: ignore[index]
    assert "releases/assets/" in script
    assert "Accept: application/octet-stream" in script
    assert "1048576" in script
    assert "8388608" in script
    assert "verify_release_identity" in script
    assert "read_release_identity" in script
    assert "draft_publish_existing" in script
    assert "orphanet-release-assets" in str(publish_steps)


def test_publisher_is_trusted_and_can_generate_provenance() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]  # type: ignore[index]
    assert "github.ref == 'refs/heads/main'" in publish["if"]
    assert "startsWith(github.ref, 'refs/tags/')" in publish["if"]
    assert "github.ref_protected == true" in publish["if"]
    assert "needs.build-and-verify.outputs.state == 'create'" in publish["if"]
    assert publish["environment"] == "data-release"
    assert publish["permissions"] == {  # type: ignore[index]
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }
    steps = publish["steps"]  # type: ignore[index]
    assert any("actions/attest-build-provenance@" in step.get("uses", "") for step in steps)
    scripts = "\n".join(_run_blocks({"jobs": {"publish": publish}}))
    assert "gh attestation verify" in scripts


def test_publisher_uses_only_the_immutable_handoff_verifier() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]  # type: ignore[index]
    steps = publish["steps"]  # type: ignore[index]
    assert any("actions/setup-python@" in step.get("uses", "") for step in steps)
    assert not any(step.get("uses", "").startswith("actions/checkout@") for step in steps)
    scripts = "\n".join(_run_blocks({"jobs": {"publish": publish}}))
    assert "uv run" not in scripts
    assert "release-package/verifier/release_identity.py" in scripts
    assert "timeout 120s" in scripts
