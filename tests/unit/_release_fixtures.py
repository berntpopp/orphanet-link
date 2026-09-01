"""Shared builders for fake GitHub release metadata and release assets.

``test_release_assets.py`` (bounded, authenticated retrieval) and
``test_release_asset_resume.py`` (which existing release may be resumed or treated
as a no-op) both need the same three shapes: an asset entry as the GitHub API
advertises it, a release object, and a manifest that passes
``release_identity._validate_manifest``. They live here so neither test module
grows past the repository's per-file line budget.
"""

from __future__ import annotations

import hashlib
import json

TAG = "data-1.3.42-4.1.8-2025-03-03-r20260623T075350Z-r2"
REPO = "berntpopp/orphanet-link"
TEST_TOKEN = "test"  # noqa: S105 - controlled mock credential


def make_asset(name: str, content: bytes, identifier: int) -> dict[str, object]:
    """One asset entry exactly as the release API advertises it."""
    return {
        "id": identifier,
        "name": name,
        "size": len(content),
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "url": f"https://api.github.com/repos/{REPO}/releases/assets/{identifier}",
    }


def make_release(
    assets: list[dict[str, object]],
    *,
    release_id: int = 99,
    tag_name: str = TAG,
    target_commitish: str = "reviewed-source",
    draft: bool = False,
    immutable: bool = True,
) -> dict[str, object]:
    """One release object as returned by the release-by-tag and inventory endpoints."""
    return {
        "id": release_id,
        "tag_name": tag_name,
        "target_commitish": target_commitish,
        "draft": draft,
        "immutable": immutable,
        "assets": assets,
    }


def make_manifest(**overrides: object) -> bytes:
    """Serialise a manifest that passes ``release_identity._validate_manifest``."""
    value: dict[str, object] = {
        "version": "1.3.42 / 4.1.8 [2025-03-03]",
        "orphanet_date": "2026-06-23 07:53:50",
        "schema_version": 1,
        "disorder_count": 2,
        "xref_count": 3,
        "gene_count": 4,
        "phenotype_count": 5,
        "prevalence_count": 6,
        "asset": "orphanet.sqlite.gz",
    }
    value.update(overrides)
    return json.dumps(value, indent=2).encode("utf-8")
