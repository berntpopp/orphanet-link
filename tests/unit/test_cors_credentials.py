"""Security guard: the unauthenticated backend must not enable CORS credentials.

The backend holds no cookies/session/auth, so `allow_credentials=True` is
meaningless and a footgun (a wildcard origin combined with credentials would be
a CSRF/credential-leak vector). This test locks `allow_credentials=False` while
preserving the existing method list and keeping the plain endpoints reachable.
Research use only; not clinical decision support."""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from orphanet_link.app import create_app


def _cors_options() -> dict[str, object]:
    app = create_app()
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return dict(mw.kwargs)
    raise AssertionError("CORSMiddleware is not installed on the app")


def test_cors_credentials_disabled() -> None:
    opts = _cors_options()
    assert opts["allow_credentials"] is False, (
        "unauthenticated backend must not allow CORS credentials"
    )


def test_cors_preserves_method_list() -> None:
    opts = _cors_options()
    # The backend serves GET (/health, /) and POST (/mcp); the method list must
    # not be collapsed to POST-only or the GET endpoints break preflight.
    assert set(opts["allow_methods"]) >= {"GET", "POST", "OPTIONS"}


async def test_health_still_reachable() -> None:
    # Use the repo's AsyncClient/ASGITransport pattern (see
    # tests/conformance/test_health_transport.py): the deprecated
    # httpx-backed TestClient can stall under the installed Starlette/httpx
    # stack, so drive the app in-process over ASGI instead.
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
