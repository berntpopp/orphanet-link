"""Tests for bounded, exact GitHub release-asset retrieval."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from orphanet_link.ingest.release_assets import (
    MAX_METADATA_BYTES,
    ReleaseAssetError,
    fetch_existing_release,
)

TAG = "data-1.3.42-4.1.8-2025-03-03"
REPO = "berntpopp/orphanet-link"
TEST_TOKEN = "test"  # noqa: S105 - controlled mock credential


def _asset(name: str, content: bytes, identifier: int) -> dict[str, object]:
    return {
        "id": identifier,
        "name": name,
        "size": len(content),
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "url": f"https://api.github.com/repos/{REPO}/releases/assets/{identifier}",
    }


def _release(assets: list[dict[str, object]]) -> dict[str, object]:
    return {"draft": False, "assets": assets}


def test_rejects_missing_or_extra_remote_asset_inventory(tmp_path: Path) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("unexpected", b"x", 2)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets), request=request)

    with pytest.raises(ReleaseAssetError, match="exact asset inventory"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_oversized_metadata_before_body_consumption(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_METADATA_BYTES + 1)},
            content=b"ignored",
            request=request,
        )

    with pytest.raises(ReleaseAssetError, match="metadata"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_non_404_release_api_status(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(ReleaseAssetError, match="HTTP 503"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.parametrize("identifier", [None, 0, -1, True, "7"])
def test_rejects_missing_or_invalid_asset_ids(tmp_path: Path, identifier: object) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("orphanet.sqlite.gz", b"gzip", 2)]
    assets.append(_asset("orphanet.sqlite.gz.sha256", b"checksum", 3))
    assets[0]["id"] = identifier

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets), request=request)

    with pytest.raises(ReleaseAssetError, match="asset"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_duplicate_asset_ids(tmp_path: Path) -> None:
    assets = [
        _asset("manifest.json", b"{}", 1),
        _asset("orphanet.sqlite.gz", b"gzip", 1),
        _asset("orphanet.sqlite.gz.sha256", b"checksum", 3),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets), request=request)

    with pytest.raises(ReleaseAssetError, match="asset"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_asset_url_not_bound_to_api_id(tmp_path: Path) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("orphanet.sqlite.gz", b"gzip", 2)]
    assets.append(_asset("orphanet.sqlite.gz.sha256", b"checksum", 3))
    assets[0]["url"] = f"https://release-assets.githubusercontent.com/assets/{assets[0]['id']}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets), request=request)

    with pytest.raises(ReleaseAssetError, match="URL"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_unapproved_asset_redirect_before_following_it(tmp_path: Path) -> None:
    manifest = b"{}"
    bundle = b"gzip"
    checksum = b"checksum"
    assets = [
        _asset("manifest.json", manifest, 1),
        _asset("orphanet.sqlite.gz", bundle, 2),
        _asset("orphanet.sqlite.gz.sha256", checksum, 3),
    ]
    blocked = "https://evil.example.invalid/release-asset"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(200, json=_release(assets), request=request)
        if request.url.path.endswith("/assets/1"):
            assert request.headers["authorization"] == "Bearer test"
            return httpx.Response(302, headers={"Location": blocked}, request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    with pytest.raises(ReleaseAssetError, match="not allowed"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )
