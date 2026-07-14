"""Repository-level docs and CI contracts that keep router integration honest."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_typecheck_is_strict_and_uses_local_make_gate() -> None:
    """GitHub CI must not silently pass mypy failures."""
    workflow = _read(".github/workflows/ci.yml")
    assert "continue-on-error" not in workflow
    assert re.search(r"run:\s*make (?:typecheck|ci-local)\b", workflow)


def test_github_action_pin_check_recurses_and_rejects_version_tags(tmp_path: Path) -> None:
    """The action pin gate must inspect nested workflows and composite actions."""
    actions = tmp_path / ".github" / "actions" / "setup"
    actions.mkdir(parents=True)
    workflow = actions / "action.yml"
    workflow.write_text(
        "runs:\n  using: composite\n  steps:\n    - uses: astral-sh/setup-uv@v6 # v6\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 -- invokes the repository's checked-in verifier.
        [sys.executable, "scripts/check_github_action_pins.py", "--root", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".github/actions/setup/action.yml:4" in result.stdout
    assert "must use a full 40-character commit SHA" in result.stdout


def test_github_action_pin_check_rejects_mutable_docker_actions(tmp_path: Path) -> None:
    """Docker action images are mutable unless they are separately digest-checked."""
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "jobs:\n  verify:\n    steps:\n      - uses: docker://alpine:latest\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 -- invokes the repository's checked-in verifier.
        [sys.executable, "scripts/check_github_action_pins.py", "--root", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".github/workflows/ci.yml:4" in result.stdout
    assert "Docker actions are not permitted" in result.stdout


def test_transport_docs_route_router_mcp_through_unified_only() -> None:
    """Router-facing docs distinguish unified MCP from REST-only http mode.

    Under README Standard v1 the deployment runbook lives in docs/deployment.md,
    so the contract is asserted there *and* the README must link to it — a reader
    who starts at the front door still reaches the footgun.
    """
    env_example = _read(".env.example")
    readme = _read("README.md")
    deployment = _read("docs/deployment.md")
    router_snippet = _read("docs/router/servers.yaml.snippet")

    assert "http (FastAPI REST/health only; no MCP endpoint)" in env_example
    assert "Router deployments must run `--transport unified`" in deployment
    assert "`--transport unified` deployment" in router_snippet

    # The README must warn about the mode split and route the reader to the runbook.
    # Whitespace-normalised so the assertion survives a re-wrap of the paragraph.
    readme_flat = " ".join(readme.split())
    assert "(docs/deployment.md)" in readme
    assert "`--transport http` is REST/health-only" in readme_flat


def test_readme_places_research_warning_in_discovery_not_every_payload() -> None:
    """Ordinary payloads must never be claimed to carry a clinical-use flag.

    The design divergence (warning surfaced through discovery, not stamped on every
    payload) is documented in docs/architecture.md; the README keeps the
    above-the-fold callout and links there.
    """
    readme = _read("README.md")
    architecture = _read("docs/architecture.md")
    false_claim = "Every payload carries an `unsafe_for_clinical_use` signal"

    assert false_claim not in readme
    assert false_claim not in architecture

    # The discovery surfaces that do carry the warning are named where it is documented.
    assert "`get_server_capabilities`" in architecture
    assert "`orphanet://research-use`" in architecture
    assert "`get_server_capabilities`" in readme

    # The README keeps the research-use callout above the fold and links to the contract.
    assert "> [!IMPORTANT]" in readme
    assert "Research use only. Not clinical decision support." in readme
    assert "(docs/architecture.md)" in readme
