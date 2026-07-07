"""Guard: pyproject -> installed metadata -> __version__ -> serverInfo -> /health are one value."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from orphanet_link import __version__
from orphanet_link.app import create_app
from orphanet_link.buildinfo import build_info
from orphanet_link.mcp.facade import create_orphanet_mcp

DIST = "orphanet-link"


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_pyproject_is_the_single_source() -> None:
    assert version(DIST) == _pyproject_version()


def test_dunder_version_is_metadata_derived() -> None:
    assert __version__ == version(DIST)
    assert build_info()["version"] == version(DIST)


def test_mcp_server_info_version_matches_package() -> None:
    assert create_orphanet_mcp().version == version(DIST)


def test_health_version_matches_package() -> None:
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == version(DIST)


def test_git_sha_never_surfaces_literal_unknown(monkeypatch) -> None:
    # The Docker build injects ORPHANET_LINK_GIT_SHA=unknown when no sha
    # build-arg is passed; that sentinel must be normalized to None, never
    # surfaced on /health or in diagnostics as the literal string "unknown".
    import orphanet_link.buildinfo as bi

    monkeypatch.setenv("ORPHANET_LINK_GIT_SHA", "unknown")
    monkeypatch.setattr(bi, "_git_sha_from_dotgit", lambda: None)
    assert bi.build_info()["git_sha"] is None


def test_git_sha_env_value_is_used_when_present(monkeypatch) -> None:
    import orphanet_link.buildinfo as bi

    monkeypatch.setenv("ORPHANET_LINK_GIT_SHA", "abc123def456")
    assert bi.build_info()["git_sha"] == "abc123def456"
