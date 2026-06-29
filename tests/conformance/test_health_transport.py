"""Unit test: /health returns {status, version, transport} per Transport Standard v1."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_health_has_status_version_transport() -> None:
    """GET /health must include status, version, and transport keys."""
    from orphanet_link.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok", f"missing/wrong 'status': {body}"
    assert "version" in body, f"missing 'version': {body}"
    assert body.get("transport") == "streamable-http-stateless", (
        f"missing/wrong 'transport': {body}"
    )
