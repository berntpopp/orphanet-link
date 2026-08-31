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


def test_release_tag_is_qualified_by_the_exact_dataset_revision() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "publication_tag" in workflow_text
    assert "orphanet_date" in workflow_text
    assert "collision_revision=2" in (ROOT / "orphanet_link/ingest/release_identity.py").read_text()
    assert 'TAG="data-$SLUG"' not in workflow_text


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
    # Every accepted release is produced from the reviewed main branch.  A
    # mutable tag ref must never become an equivalent signer identity.
    assert workflow_text.count('--source-ref "refs/heads/main"') == checks
    assert '--source-ref "$GITHUB_REF"' not in workflow_text
    # A different workflow identity, including a caller-controlled value, must
    # not be accepted by any of the release attestation checks.
    assert '--signer-workflow "$GITHUB_REPOSITORY' not in workflow_text


def test_build_and_publisher_permissions_are_separated() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "orphanet-data-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    jobs = workflow["jobs"]
    assert jobs["build-and-verify"]["permissions"] == {"contents": "read"}  # type: ignore[index]
    assert jobs["publish"]["permissions"] == {  # type: ignore[index]
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_create_binds_api_identity_and_does_not_use_an_overwriting_action() -> None:
    workflow = _workflow()
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "softprops/action-gh-release" not in workflow_text
    assert "gh api --method POST" in workflow_text
    assert "gh release create" not in workflow_text
    assert "--clobber" not in workflow_text
    publish_steps = workflow["jobs"]["publish"]["steps"]  # type: ignore[index]
    create = next(
        step for step in publish_steps if step.get("name") == "Create and upload exact-ID draft"
    )
    assert create["id"] == "create_draft"
    script = create["run"]
    assert "created release response" in script
    assert "inventory_tag" not in script
    assert "upload_asset" in script
    assert "release_id=$release_id" in script


def test_publisher_refetches_and_reverifies_the_draft_immediately_before_publish() -> None:
    """The build-job check cannot authorize a mutable draft minutes later."""
    workflow = _workflow()
    publish_steps = workflow["jobs"]["publish"]["steps"]  # type: ignore[index]
    names = [step.get("name", "") for step in publish_steps]  # type: ignore[union-attr]
    create_draft = names.index("Create and upload exact-ID draft")
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
    assert 'gh release view "$TAG"' not in script
    assert 'gh release edit "$TAG"' not in script
    assert "RELEASE_ID" in script
    assert "releases/$release_id" in script
    patch = script.index("gh api --method PATCH")
    assert script.index('"repos/$GITHUB_REPOSITORY/releases/$release_id"', patch) > patch
    assert "git/ref/tags/$TAG" in script
    assert "orphanet-release-assets" in str(publish_steps)


def test_published_noop_rechecks_release_identity_and_source_tag() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    build = workflow_text[
        workflow_text.index("Verify existing release identity") : workflow_text.index(
            "# 5. Transfer"
        )
    ]
    assert "immutable" in build
    assert "target_commitish" in build
    assert "git/ref/tags/$TAG" in build
    assert "releases/$release_id" in build


def test_selected_draft_id_crosses_the_build_publisher_boundary() -> None:
    workflow = _workflow()
    build = workflow["jobs"]["build-and-verify"]  # type: ignore[index]
    publish = workflow["jobs"]["publish"]  # type: ignore[index]
    assert build["outputs"]["release_id"] == "${{ steps.release_state.outputs.release_id }}"
    publish_step = next(
        step for step in publish["steps"] if step.get("name") == "Publish exact rechecked draft"
    )
    assert publish_step["env"]["RELEASE_ID"] == (
        "${{ needs.build-and-verify.outputs.release_id || steps.create_draft.outputs.release_id }}"
    )
    assert not any(step.get("name") == "Bind existing exact draft ID" for step in publish["steps"])


def test_created_release_id_is_refetched_and_bound_before_publishing() -> None:
    workflow = _workflow()
    publish_steps = workflow["jobs"]["publish"]["steps"]  # type: ignore[index]
    create = next(
        step for step in publish_steps if step.get("name") == "Create and upload exact-ID draft"
    )
    script = create["run"]
    assert "releases/$release_id" in script
    assert "release API identity changed unexpectedly" in script


def test_create_uses_api_response_id_without_replacing_it_from_tag_inventory() -> None:
    workflow = _workflow()
    create = next(
        step
        for step in workflow["jobs"]["publish"]["steps"]  # type: ignore[index]
        if step.get("name") == "Create and upload exact-ID draft"
    )
    script = create["run"]
    assert "gh api --method POST" in script
    assert "created release response" in script
    assert 'inventory_tag "$after"' not in script


def test_annotated_source_tags_are_explicitly_rejected() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "lightweight commit" in workflow_text
    assert workflow_text.count('target.get("type") != "commit"') >= 3


def test_writer_bounds_ids_and_times_out_create() -> None:
    workflow_text = (ROOT / ".github/workflows/build-data.yml").read_text()
    assert "2**63 - 1" in workflow_text
    assert "timeout 30s gh api --method POST" in workflow_text
    assert "timeout 120s gh api --method POST" in workflow_text


def test_publisher_is_trusted_and_can_generate_provenance() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]  # type: ignore[index]
    assert "github.ref == 'refs/heads/main'" in publish["if"]
    # Tag dispatches can build and verify read-only, but must never obtain the
    # privileged publisher: tag provenance cannot satisfy the main-only
    # release identity contract.
    assert "startsWith(github.ref, 'refs/tags/')" not in publish["if"]
    assert "github.ref_protected == true" in publish["if"]
    assert "needs.build-and-verify.outputs.state == 'create'" in publish["if"]
    assert publish["environment"] == "data-release"
    assert publish["permissions"] == {  # type: ignore[index]
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }
    steps = publish["steps"]  # type: ignore[index]
    assert any(
        step.get("uses")
        == "actions/attest-build-provenance@520d128f165991a6c774bcb264f323e3d70747f4"
        for step in steps
    )
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
