"""Tests for bounded Orphanet release identity and collision decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orphanet_link.ingest.release_identity import (
    ReleaseIdentityError,
    classify_release,
    manifest_identity,
    publication_tag,
    read_release_identity,
    release_tag,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "releases" / "orphanet_data_1.3.42.json"
)
TAG = "data-1.3.42-4.1.8-2025-03-03-r20251209T070632Z"
COLLISION_DATE = "2026-06-23 07:53:50"
COLLISION_TAG = "data-1.3.42-4.1.8-2025-03-03-r20260623T075350Z"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_release_tag_binds_the_dataset_revision() -> None:
    version = "1.3.42 / 4.1.8 [2025-03-03]"

    assert release_tag(version, "2025-12-09 07:06:32") == TAG
    assert release_tag(version, COLLISION_DATE) == COLLISION_TAG
    assert release_tag(version, COLLISION_DATE, collision_revision=3) == f"{COLLISION_TAG}-r3"

    with pytest.raises(ReleaseIdentityError, match="orphanet_date"):
        release_tag(version, "2026-06-23")

    for invalid_revision in (True, 1, 0, -1, 2, "3"):
        with pytest.raises(ReleaseIdentityError, match="collision revision"):
            release_tag(  # type: ignore[arg-type]
                version,
                COLLISION_DATE,
                collision_revision=invalid_revision,
            )


def test_collision_revision_is_only_for_the_audited_source_tuple() -> None:
    version = "1.3.42 / 4.1.8 [2025-03-03]"
    audited_date = COLLISION_DATE
    prior_date = "2025-12-09 07:06:32"
    future_version = "1.3.43 / 4.1.9 [2026-01-01]"

    assert publication_tag(version, audited_date).endswith("-r3")
    assert publication_tag(version, prior_date) == release_tag(version, prior_date)
    assert publication_tag(future_version, audited_date) == release_tag(
        future_version, audited_date
    )
    with pytest.raises(ReleaseIdentityError, match="audited source"):
        release_tag(future_version, audited_date, collision_revision=3)
    with pytest.raises(ReleaseIdentityError, match="audited source"):
        release_tag(version, prior_date, collision_revision=3)
    with pytest.raises(ReleaseIdentityError, match="exactly revision 3"):
        release_tag(version, audited_date, collision_revision=2)


def test_tag_only_existing_release_cannot_be_skipped(tmp_path: Path) -> None:
    current = _fixture()
    with pytest.raises(ReleaseIdentityError, match="exact release assets"):
        classify_release(current, {"tag": current["tag"]}, is_draft=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["bundle_sha256", "bundle_size", "manifest"])
def test_any_identity_difference_is_a_collision(field: str) -> None:
    current = _fixture()
    existing = json.loads(json.dumps(current))
    if field == "bundle_sha256":
        existing[field] = "0" * 64
    elif field == "bundle_size":
        existing[field] = 1
    else:
        existing["manifest"]["schema_version"] = 99  # type: ignore[index]

    assert classify_release(current, existing, is_draft=False) == "collision"  # type: ignore[arg-type]
    assert classify_release(current, existing, is_draft=True) == "collision"  # type: ignore[arg-type]


def test_identical_published_and_draft_states_are_distinct() -> None:
    current = _fixture()
    assert classify_release(current, current, is_draft=False) == "published_noop"  # type: ignore[arg-type]
    assert classify_release(current, current, is_draft=True) == "draft_publish_existing"  # type: ignore[arg-type]
    assert classify_release(current, None, is_draft=False) == "create"  # type: ignore[arg-type]


def test_equal_malformed_identities_fail_closed() -> None:
    malformed: dict[str, object] = {
        "tag": 7,
        "assets": [],
        "bundle_sha256": None,
        "bundle_size": "large",
        "manifest": [],
    }

    with pytest.raises(ReleaseIdentityError, match="invalid"):
        classify_release(malformed, malformed, is_draft=False)


def test_read_release_identity_requires_exact_assets_and_bounded_metadata(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseIdentityError, match="exact release assets"):
        read_release_identity(tmp_path, TAG)


def _write_release(
    path: Path, *, schema_version: int = 1, orphanet_date: str = "2025-12-09 07:06:32"
) -> None:
    path.mkdir()
    asset = b"bounded test sqlite gzip bytes"
    digest = hashlib.sha256(asset).hexdigest()
    (path / "orphanet.sqlite.gz").write_bytes(asset)
    (path / "orphanet.sqlite.gz.sha256").write_text(f"{digest}  orphanet.sqlite.gz\n")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "1.3.42 / 4.1.8 [2025-03-03]",
                "orphanet_date": orphanet_date,
                "schema_version": schema_version,
                "disorder_count": 1,
                "xref_count": 2,
                "gene_count": 3,
                "phenotype_count": 4,
                "prevalence_count": 5,
                "build_utc": "2026-08-31T00:00:00+00:00",
                "asset": "orphanet.sqlite.gz",
            }
        )
    )


def test_directory_identity_verifies_assets_and_schema_before_classifying(tmp_path: Path) -> None:
    current = tmp_path / "current"
    existing = tmp_path / "existing"
    _write_release(current, orphanet_date=COLLISION_DATE)
    _write_release(existing, orphanet_date=COLLISION_DATE)

    assert read_release_identity(current, COLLISION_TAG).bundle_size == 30
    assert read_release_identity(existing, COLLISION_TAG).schema_version == 1
    assert read_release_identity(current, f"{COLLISION_TAG}-r3").tag == f"{COLLISION_TAG}-r3"

    with pytest.raises(ReleaseIdentityError, match="manifest version"):
        read_release_identity(current, f"{COLLISION_TAG}-r1")
    with pytest.raises(ReleaseIdentityError, match="manifest version"):
        read_release_identity(current, f"{COLLISION_TAG}-r2")
    with pytest.raises(ReleaseIdentityError, match="manifest version"):
        read_release_identity(current, f"{COLLISION_TAG}-r4")

    (existing / "manifest.json").write_text(
        (existing / "manifest.json")
        .read_text()
        .replace('"schema_version": 1', '"schema_version": 2')
    )
    from orphanet_link.ingest.release_identity import verify_release_identity

    assert verify_release_identity(current, existing, COLLISION_TAG, is_draft=False) == "collision"


def test_directory_identity_rejects_checksum_or_extra_asset(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _write_release(release)
    (release / "orphanet.sqlite.gz.sha256").write_text("0" * 64 + "  orphanet.sqlite.gz\n")
    with pytest.raises(ReleaseIdentityError, match="checksum"):
        read_release_identity(release, TAG)

    (release / "orphanet.sqlite.gz.sha256").write_text(
        hashlib.sha256(b"bounded test sqlite gzip bytes").hexdigest() + "  orphanet.sqlite.gz\n"
    )
    (release / "unexpected").write_text("no")
    with pytest.raises(ReleaseIdentityError, match="exact release assets"):
        read_release_identity(release, TAG)


def _manifest_bytes(**overrides: object) -> bytes:
    manifest: dict[str, object] = {
        "version": "1.3.42 / 4.1.8 [2025-03-03]",
        "orphanet_date": COLLISION_DATE,
        "schema_version": 1,
        "disorder_count": 1,
        "xref_count": 2,
        "gene_count": 3,
        "phenotype_count": 4,
        "prevalence_count": 5,
        "asset": "orphanet.sqlite.gz",
    }
    manifest.update(overrides)
    return json.dumps(manifest).encode("utf-8")


def test_manifest_identity_ignores_build_provenance() -> None:
    """``build_utc`` says when a build ran, so it cannot be part of an identity."""
    baseline = manifest_identity(_manifest_bytes())

    assert manifest_identity(_manifest_bytes(build_utc="2026-08-31T00:00:00+00:00")) == baseline
    assert manifest_identity(_manifest_bytes(build_utc="2026-09-01T09:15:00+00:00")) == baseline
    # Everything that describes the *content* still separates two manifests.
    assert manifest_identity(_manifest_bytes(disorder_count=99)) != baseline
    assert manifest_identity(_manifest_bytes(schema_version=2)) != baseline
    assert manifest_identity(_manifest_bytes(orphanet_date="2025-12-09 07:06:32")) != baseline


def test_manifest_identity_rejects_a_malformed_manifest() -> None:
    with pytest.raises(ReleaseIdentityError, match="invalid JSON"):
        manifest_identity(b"not json")
    with pytest.raises(ReleaseIdentityError, match="incomplete or unexpected shape"):
        manifest_identity(b'{"version": "x"}')
    with pytest.raises(ReleaseIdentityError, match="invalid build_utc"):
        manifest_identity(_manifest_bytes(build_utc=""))
