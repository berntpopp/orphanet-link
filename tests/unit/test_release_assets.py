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


def _release(
    assets: list[dict[str, object]],
    *,
    release_id: int = 99,
    tag_name: str = TAG,
    target_commitish: str = "reviewed-source",
    draft: bool = False,
    immutable: bool = True,
) -> dict[str, object]:
    return {
        "id": release_id,
        "tag_name": tag_name,
        "target_commitish": target_commitish,
        "draft": draft,
        "immutable": immutable,
        "assets": assets,
    }


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


def test_discovers_an_authenticated_draft_when_tag_lookup_returns_404(tmp_path: Path) -> None:
    manifest = b"{}"
    bundle = b"gzip"
    checksum = b"checksum"
    assets = [
        _asset("manifest.json", manifest, 1),
        _asset("orphanet.sqlite.gz", bundle, 2),
        _asset("orphanet.sqlite.gz.sha256", checksum, 3),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(404, request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "tag_name": TAG,
                        "target_commitish": "reviewed-source",
                        "draft": True,
                        "immutable": False,
                        "assets": assets,
                    }
                ],
                request=request,
            )
        for identifier, content in ((1, manifest), (2, bundle), (3, checksum)):
            if request.url.path.endswith(f"/assets/{identifier}"):
                return httpx.Response(200, content=content, request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    result = fetch_existing_release(
        REPO,
        TAG,
        tmp_path / "release",
        token=TEST_TOKEN,
        transport=httpx.MockTransport(handler),
    )

    assert result is not None
    assert result.is_draft is True
    assert result.release_id == 7
    assert result.tag_name == TAG
    assert {path.name for path in (tmp_path / "release").iterdir()} == {
        "manifest.json",
        "orphanet.sqlite.gz",
        "orphanet.sqlite.gz.sha256",
    }


def test_resumes_partial_draft_only_when_existing_asset_matches_package(tmp_path: Path) -> None:
    content = b"matching manifest"
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(content)
    assets = [_asset("manifest.json", content, 1)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(404, request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(
                200,
                json=[_release(assets, release_id=7, draft=True, immutable=False)],
                request=request,
            )
        if request.url.path.endswith("/assets/1"):
            return httpx.Response(200, content=content, request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    result = fetch_existing_release(
        REPO,
        TAG,
        tmp_path / "release",
        token=TEST_TOKEN,
        expected_dir=expected,
        transport=httpx.MockTransport(handler),
    )

    assert result is not None
    assert result.is_draft is True
    assert result.complete is False
    assert (tmp_path / "release" / "manifest.json").read_bytes() == content


def test_rejects_partial_draft_asset_that_differs_from_package(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(b"expected")
    assets = [_asset("manifest.json", b"different", 1)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_release(assets, draft=True, immutable=False), request=request
        )

    with pytest.raises(ReleaseAssetError, match="does not match package"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            expected_dir=expected,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_published_release_with_wrong_response_identity(tmp_path: Path) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("orphanet.sqlite.gz", b"gzip", 2)]
    assets.append(_asset("orphanet.sqlite.gz.sha256", b"checksum", 3))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets, tag_name="other-tag"), request=request)

    with pytest.raises(ReleaseAssetError, match="tag"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_mutable_published_release(tmp_path: Path) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("orphanet.sqlite.gz", b"gzip", 2)]
    assets.append(_asset("orphanet.sqlite.gz.sha256", b"checksum", 3))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets, immutable=False), request=request)

    with pytest.raises(ReleaseAssetError, match="immutable"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_unbounded_release_id(tmp_path: Path) -> None:
    assets = [_asset("manifest.json", b"{}", 1), _asset("orphanet.sqlite.gz", b"gzip", 2)]
    assets.append(_asset("orphanet.sqlite.gz.sha256", b"checksum", 3))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_release(assets, release_id=2**63), request=request)

    with pytest.raises(ReleaseAssetError, match="release ID"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )


def test_rejects_hidden_same_tag_draft_for_published_release(tmp_path: Path) -> None:
    contents = {
        "manifest.json": b"{}",
        "orphanet.sqlite.gz": b"gzip",
        "orphanet.sqlite.gz.sha256": b"checksum",
    }
    assets = [_asset(name, body, index) for index, (name, body) in enumerate(contents.items(), 1)]
    published = _release(assets, release_id=10)
    hidden_draft = _release(assets, release_id=11, draft=True, immutable=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(200, json=published, request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[published, hidden_draft], request=request)
        for asset in assets:
            if request.url.path.endswith(f"/assets/{asset['id']}"):
                return httpx.Response(200, content=contents[asset["name"]], request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    with pytest.raises(ReleaseAssetError, match="duplicate"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            transport=httpx.MockTransport(handler),
        )
