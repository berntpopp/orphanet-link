"""Which existing release may be resumed, and which is a verified no-op.

These are the states the data pipeline must get exactly right before it mutates a
release: resume a partial draft only when the assets already uploaded are the ones
we hold, and recognise an identical published release as a no-op rather than a
collision.  Both were unreachable at one point -- see the regression notes on the
individual tests.

Bounded, authenticated retrieval itself is covered by ``test_release_assets.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from orphanet_link.ingest.release_assets import ReleaseAssetError, fetch_existing_release
from tests.unit._release_fixtures import (
    REPO,
    TAG,
    TEST_TOKEN,
    make_asset,
    make_manifest,
    make_release,
)


def _partial_draft_handler(
    assets: list[dict[str, object]],
    bodies: dict[int, bytes],
) -> Callable[[httpx.Request], httpx.Response]:
    """Serve one partial draft that GitHub hides from the release-by-tag endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(404, request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(
                200,
                json=[make_release(assets, release_id=7, draft=True, immutable=False)],
                request=request,
            )
        for identifier, content in bodies.items():
            if request.url.path.endswith(f"/assets/{identifier}"):
                return httpx.Response(200, content=content, request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    return handler


def test_resumes_partial_draft_when_the_manifest_matches_on_identity(tmp_path: Path) -> None:
    """A resumed manifest is compared on identity, not bytes.

    ``manifest.json`` records ``build_utc`` -- when the build ran, not what it
    produced.  Requiring the two files to be byte-identical would make a resume
    impossible for exactly the reason a rebuild can never reproduce a wall clock.
    """
    remote = make_manifest(build_utc="2026-06-23T07:53:50+00:00")
    local = make_manifest(build_utc="2026-09-01T09:15:00+00:00")
    assert remote != local
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(local)
    assets = [make_asset("manifest.json", remote, 1)]

    result = fetch_existing_release(
        REPO,
        TAG,
        tmp_path / "release",
        token=TEST_TOKEN,
        expected_dir=expected,
        transport=httpx.MockTransport(_partial_draft_handler(assets, {1: remote})),
    )

    assert result is not None
    assert result.is_draft is True
    assert result.complete is False
    assert (tmp_path / "release" / "manifest.json").read_bytes() == remote


def test_rejects_partial_draft_manifest_that_differs_in_an_identity_field(
    tmp_path: Path,
) -> None:
    """Identity comparison stays strict about everything except run provenance."""
    remote = make_manifest(disorder_count=2)
    local = make_manifest(disorder_count=9999)
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(local)
    assets = [make_asset("manifest.json", remote, 1)]

    with pytest.raises(ReleaseAssetError, match=r"manifest\.json does not match package"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            expected_dir=expected,
            transport=httpx.MockTransport(_partial_draft_handler(assets, {1: remote})),
        )


def test_rejects_partial_draft_bundle_that_differs_from_package(tmp_path: Path) -> None:
    """A non-manifest asset is still held to a byte-exact ``(size, sha256)``."""
    manifest = make_manifest()
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(manifest)
    (expected / "orphanet.sqlite.gz").write_bytes(b"expected bundle")
    assets = [
        make_asset("manifest.json", manifest, 1),
        make_asset("orphanet.sqlite.gz", b"a different bundle", 2),
    ]

    with pytest.raises(ReleaseAssetError, match=r"orphanet\.sqlite\.gz does not match package"):
        fetch_existing_release(
            REPO,
            TAG,
            tmp_path / "release",
            token=TEST_TOKEN,
            expected_dir=expected,
            transport=httpx.MockTransport(
                _partial_draft_handler(assets, {1: manifest, 2: b"a different bundle"})
            ),
        )


def test_complete_release_is_not_held_to_a_byte_exact_expected_package(tmp_path: Path) -> None:
    """Regression: ``published_noop`` was unreachable.

    The byte-exact ``--expected-dir`` precondition was applied to every state, so a
    complete published release whose ``manifest.json`` merely carried a different
    ``build_utc`` was rejected as "does not match package" -- which is every
    rebuild, always.  A complete release is compared by ``verify_release_identity``
    afterwards, which already treats ``build_utc`` as non-identity.
    """
    remote_manifest = make_manifest(build_utc="2026-06-23T07:53:50+00:00")
    local_manifest = make_manifest(build_utc="2026-09-01T09:15:00+00:00")
    bundle = b"gzip bytes"
    checksum = f"{hashlib.sha256(bundle).hexdigest()}  orphanet.sqlite.gz\n".encode()
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "manifest.json").write_bytes(local_manifest)
    (expected / "orphanet.sqlite.gz").write_bytes(bundle)
    (expected / "orphanet.sqlite.gz.sha256").write_bytes(checksum)
    assets = [
        make_asset("manifest.json", remote_manifest, 1),
        make_asset("orphanet.sqlite.gz", bundle, 2),
        make_asset("orphanet.sqlite.gz.sha256", checksum, 3),
    ]
    bodies = {1: remote_manifest, 2: bundle, 3: checksum}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(200, json=make_release(assets), request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[], request=request)
        for identifier, content in bodies.items():
            if request.url.path.endswith(f"/assets/{identifier}"):
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
    assert result.is_draft is False
    assert result.complete is True


def test_accepts_a_published_release_that_no_draft_shadows(tmp_path: Path) -> None:
    """Regression: the shadow-draft check demanded the published release be a draft.

    The post-download ambiguity check reuses ``_find_authenticated_draft`` to prove
    no hidden same-tag draft exists.  It also required its ``expected_release_id``
    to be *found as a draft* -- which a healthy published release never is, so every
    correct published release was rejected and ``published_noop`` was unreachable.
    """
    contents = {
        "manifest.json": make_manifest(),
        "orphanet.sqlite.gz": b"gzip",
        "orphanet.sqlite.gz.sha256": b"checksum",
    }
    assets = [
        make_asset(name, body, index) for index, (name, body) in enumerate(contents.items(), 1)
    ]
    published = make_release(assets, release_id=10)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/" + TAG):
            return httpx.Response(200, json=published, request=request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[published], request=request)
        for asset in assets:
            if request.url.path.endswith(f"/assets/{asset['id']}"):
                return httpx.Response(200, content=contents[asset["name"]], request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    result = fetch_existing_release(
        REPO,
        TAG,
        tmp_path / "release",
        token=TEST_TOKEN,
        transport=httpx.MockTransport(handler),
    )

    assert result is not None
    assert result.is_draft is False
    assert result.complete is True
    assert result.release_id == 10
