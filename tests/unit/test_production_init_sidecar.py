"""Production data-materialization boundary contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.services.refresh import bootstrap_data

ROOT = Path(__file__).resolve().parents[2]
_DATA_TAG = "data-1.3.42-4.1.8-2025-03-03"
_BUNDLE_SHA256 = "a8af3fc39cca2acedd12c188cb0e1f907ac320e73d2b965c17ad5a28c5f5fe38"


def _production_compose() -> dict[str, Any]:
    compose = (ROOT / "docker/docker-compose.prod.yml").read_text(encoding="utf-8")
    return yaml.safe_load(compose.replace("!reset", "").replace("!override", ""))


def _npm_compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "docker/docker-compose.npm.yml").read_text(encoding="utf-8"))


def _environment(values: list[str]) -> dict[str, str]:
    return dict(value.split("=", maxsplit=1) for value in values)


def test_production_uses_hardened_init_to_materialize_the_pinned_snapshot() -> None:
    """The only production writer is a one-shot sidecar fetching the fixed release."""
    compose = _production_compose()
    init = compose["services"]["orphanet-data-init"]

    assert init["image"] == (
        "${ORPHANET_LINK_IMAGE:?ORPHANET_LINK_IMAGE must be set to "
        "ghcr.io/berntpopp/orphanet-link@sha256:<digest>}"
    )
    assert init["pull_policy"] == "missing"
    assert init["entrypoint"] == ["orphanet-link-data", "fetch"]
    assert init["environment"] == {
        "ORPHANET_LINK_DATA__DATA_DIR": f"/data/{_DATA_TAG}",
        "ORPHANET_LINK_DATA__RELEASE_TAG": _DATA_TAG,
        "ORPHANET_LINK_DATA__BUNDLE_EXPECTED_SHA256": _BUNDLE_SHA256,
    }
    assert init["volumes"] == ["orphanet-data:/data"]
    assert init["read_only"] is True
    assert init["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=256m,mode=1777"]  # noqa: S108
    assert init["security_opt"] == ["no-new-privileges:true"]
    assert init["cap_drop"] == ["ALL"]
    assert init["init"] is True
    assert init["restart"] == "no"
    assert init["deploy"]["resources"]["limits"] == {
        "memory": "512m",
        "cpus": "0.5",
        "pids": 128,
    }
    assert init["logging"]["driver"] == "json-file"
    assert init["logging"]["options"] == {"max-size": "10m", "max-file": "3"}
    assert "ports" not in init
    assert "expose" not in init


def test_production_app_waits_for_the_read_only_pinned_snapshot() -> None:
    """The serving process cannot create, change, or bootstrap its reference data."""
    compose = _production_compose()
    app = compose["services"]["orphanet-link"]

    assert app["depends_on"] == {
        "orphanet-data-init": {"condition": "service_completed_successfully"}
    }
    assert app["environment"]["ORPHANET_LINK_DATA__DATA_DIR"] == f"/data/{_DATA_TAG}"
    assert app["environment"]["ORPHANET_LINK_DATA__AUTO_BOOTSTRAP"] == "false"
    assert app["environment"]["ORPHANET_LINK_DATA__REFRESH_ENABLED"] == "false"
    assert app["volumes"] == ["orphanet-data:/data:ro"]


def test_release_manifest_declares_the_init_role_and_immutable_bundle_smoke() -> None:
    """The release declaration must describe the Compose topology honestly."""
    release = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))

    assert release["data"]["release_tag"] == _DATA_TAG
    assert release["data"]["digest"] == f"sha256:{_BUNDLE_SHA256}"
    assert release["service"]["auxiliary"] == [
        {
            "name": "orphanet-data-init",
            "role": "init",
            "egress": "approved-networks",
            "writable_targets": ["/data", "/tmp"],  # noqa: S108
        }
    ]
    assert release["smoke"]["profile"] == "immutable-bundle"


def test_npm_deploy_uses_the_same_init_sidecar_boundary() -> None:
    """The standalone production overlay cannot bypass the immutable snapshot design."""
    compose = _npm_compose()
    init = compose["services"]["orphanet-data-init"]
    app = compose["services"]["orphanet_link"]

    assert init["entrypoint"] == ["orphanet-link-data", "fetch"]
    assert _environment(init["environment"]) == {
        "ORPHANET_LINK_DATA__DATA_DIR": f"/data/{_DATA_TAG}",
        "ORPHANET_LINK_DATA__RELEASE_TAG": _DATA_TAG,
        "ORPHANET_LINK_DATA__BUNDLE_EXPECTED_SHA256": _BUNDLE_SHA256,
    }
    assert init["volumes"] == ["orphanet-data:/data"]
    assert init["restart"] == "no"
    assert app["depends_on"] == {
        "orphanet-data-init": {"condition": "service_completed_successfully"}
    }
    environment = _environment(app["environment"])
    assert environment["ORPHANET_LINK_DATA__DATA_DIR"] == f"/data/{_DATA_TAG}"
    assert environment["ORPHANET_LINK_DATA__AUTO_BOOTSTRAP"] == "false"
    assert app["volumes"] == ["orphanet-data:/data:ro"]


def test_current_docs_distinguish_local_bootstrap_from_production_sidecar() -> None:
    """Operators must not reintroduce in-app production acquisition from old runbooks."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    data = (ROOT / "docs/data.md").read_text(encoding="utf-8")
    configuration = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")

    assert "hardened `orphanet-data-init` sidecar" in deployment
    assert "read-only snapshot" in deployment
    assert "Production uses the hardened init sidecar" in readme
    assert "Production uses its hardened init sidecar" in data
    assert "DATA__BUNDLE_EXPECTED_SHA256" in configuration
    assert "On first boot the entrypoint bootstraps" not in deployment


@pytest.mark.asyncio
async def test_bootstrap_data_does_not_invoke_the_resolver_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Production turns auto-bootstrap off, so the app never takes the egress path."""
    calls: list[OrphanetDataConfig] = []

    def _unexpected_resolver(config: OrphanetDataConfig) -> Path:
        calls.append(config)
        return config.db_path

    monkeypatch.setattr(
        "orphanet_link.services.data_resolver.ensure_database", _unexpected_resolver
    )
    logger = _Logger()

    await bootstrap_data(OrphanetDataConfig(data_dir=tmp_path, auto_bootstrap=False), logger)

    assert calls == []
    assert logger.events == [("info", "orphanet_data_bootstrap_disabled")]


class _Logger:
    """Small structured-logger spy for bootstrap policy tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def info(self, event: str, **_kwargs: object) -> None:
        self.events.append(("info", event))
