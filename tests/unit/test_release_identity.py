"""Tests for bounded Orphanet release identity and collision decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orphanet_link.ingest.release_identity import (
    ReleaseIdentityError,
    classify_release,
    read_release_identity,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "releases" / "orphanet_data_1.3.42.json"
)
TAG = "data-1.3.42-4.1.8-2025-03-03"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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


def _write_release(path: Path, *, schema_version: int = 1) -> None:
    path.mkdir()
    asset = b"bounded test sqlite gzip bytes"
    digest = hashlib.sha256(asset).hexdigest()
    (path / "orphanet.sqlite.gz").write_bytes(asset)
    (path / "orphanet.sqlite.gz.sha256").write_text(f"{digest}  orphanet.sqlite.gz\n")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "1.3.42 / 4.1.8 [2025-03-03]",
                "orphanet_date": "2025-03-03",
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
    _write_release(current)
    _write_release(existing)

    assert read_release_identity(current, TAG).bundle_size == 30
    assert read_release_identity(existing, TAG).schema_version == 1

    (existing / "manifest.json").write_text(
        (existing / "manifest.json")
        .read_text()
        .replace('"schema_version": 1', '"schema_version": 2')
    )
    from orphanet_link.ingest.release_identity import verify_release_identity

    assert verify_release_identity(current, existing, TAG, is_draft=False) == "collision"


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
