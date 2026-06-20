"""Repository-level docs and CI contracts that keep router integration honest."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_typecheck_is_strict_and_uses_local_make_gate() -> None:
    """GitHub CI must not silently pass mypy failures."""
    workflow = _read(".github/workflows/ci.yml")
    assert "continue-on-error" not in workflow
    assert re.search(r"run:\s*make (?:typecheck|ci-local)\b", workflow)


def test_transport_docs_route_router_mcp_through_unified_only() -> None:
    """Router-facing docs distinguish unified MCP from REST-only http mode."""
    env_example = _read(".env.example")
    readme = _read("README.md")
    router_snippet = _read("docs/router/servers.yaml.snippet")

    assert "http (FastAPI REST/health only; no MCP endpoint)" in env_example
    assert "Router deployments must run `--transport unified`" in readme
    assert "`--transport unified` deployment" in router_snippet


def test_readme_places_research_warning_in_discovery_not_every_payload() -> None:
    """README must not claim ordinary payloads carry a clinical-use flag."""
    readme = _read("README.md")
    assert "Every payload carries an `unsafe_for_clinical_use` signal" not in readme
    assert "`get_server_capabilities`" in readme
    assert "`orphanet://research-use`" in readme
