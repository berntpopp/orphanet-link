"""The runtime data identity contract: /health readiness and the controller probe.

`/health` is what the fleet controller reads to decide whether a deployment is serving
the data release it was configured for, and `python -m orphanet_link.data_probe` is what
it execs to observe that data semantically. Both are external contracts: their exact key
sets are asserted here, not just their happy path.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orphanet_link.app import create_app
from orphanet_link.config import OrphanetDataConfig, settings
from orphanet_link.data_probe import DataProbeError, probe
from orphanet_link.data_probe import main as data_probe_main
from orphanet_link.runtime_data_identity import (
    IDENTITY_FILENAME,
    RuntimeDataIdentityError,
    build_identity_manifest,
    verify_runtime_identity,
    write_identity_manifest,
)
from orphanet_link.services.data_resolver import _db_is_valid, _record_identity

RELEASE_TAG = "data-1.3.42-4.1.8-2025-03-03-r20260623T075350Z-r2"
BUNDLE_SHA256 = "cc32164c7f64bfb053fabdb2c739ff0236cc039000d3827e7c64160d70dec62f"
DB_FILENAME = "orphanet.sqlite"


def _database(root: Path, *, codes: tuple[str, ...] = ("166024", "10", "93419")) -> Path:
    """Write a minimal store carrying only what the probe reads."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / DB_FILENAME
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE meta (id INTEGER PRIMARY KEY, schema_version INTEGER)")
        connection.execute("INSERT INTO meta (id, schema_version) VALUES (1, 1)")
        connection.execute("CREATE TABLE disorder (orpha_code TEXT PRIMARY KEY, name TEXT)")
        connection.executemany(
            "INSERT INTO disorder (orpha_code, name) VALUES (?, ?)",
            [(code, f"disorder {code}") for code in codes],
        )
    connection.close()
    return path


def _materialize(root: Path, *, bundle_sha256: str = BUNDLE_SHA256) -> Path:
    _database(root)
    write_identity_manifest(
        root,
        build_identity_manifest(
            root,
            release_tag=RELEASE_TAG,
            bundle_sha256=bundle_sha256,
            database=DB_FILENAME,
        ),
    )
    return root


def _pinned(root: Path, *, bundle_sha256: str = BUNDLE_SHA256) -> OrphanetDataConfig:
    return OrphanetDataConfig(
        data_dir=root,
        release_tag=RELEASE_TAG,
        bundle_expected_sha256=bundle_sha256,
        auto_bootstrap=False,
        refresh_enabled=False,
    )


# --------------------------------------------------------------------------- identity


def test_verified_identity_is_the_declared_release_tag_and_bundle_digest(tmp_path: Path) -> None:
    """The proven pair is exactly what container-release.json declares."""
    root = _materialize(tmp_path / "data")

    assert verify_runtime_identity(root, database=DB_FILENAME) == {
        "release_tag": RELEASE_TAG,
        "digest": f"sha256:{BUNDLE_SHA256}",
    }


def test_changed_database_bytes_invalidate_the_recorded_identity(tmp_path: Path) -> None:
    """The manifest is a claim about bytes; it is re-checked against the bytes."""
    root = _materialize(tmp_path / "data")
    (root / DB_FILENAME).write_bytes((root / DB_FILENAME).read_bytes() + b"\x00")

    with pytest.raises(RuntimeDataIdentityError):
        verify_runtime_identity(root, database=DB_FILENAME)


def test_a_missing_manifest_is_not_an_identity(tmp_path: Path) -> None:
    """Data without a manifest cannot prove anything, however valid the database is."""
    root = tmp_path / "data"
    _database(root)

    with pytest.raises(RuntimeDataIdentityError):
        verify_runtime_identity(root, database=DB_FILENAME)


def test_a_mutable_release_tag_can_never_be_an_identity(tmp_path: Path) -> None:
    """`latest` moves, so it cannot name the release a deployment is bound to."""
    root = tmp_path / "data"
    _database(root)

    with pytest.raises(RuntimeDataIdentityError):
        build_identity_manifest(
            root, release_tag="latest", bundle_sha256=BUNDLE_SHA256, database=DB_FILENAME
        )


def test_an_unpinned_store_declares_no_expected_identity(tmp_path: Path) -> None:
    """Development resolves `latest` and declares no digest: nothing to prove."""
    assert OrphanetDataConfig(data_dir=tmp_path).expected_data_identity() is None


# ----------------------------------------------------------------------------- health


def _health(monkeypatch: pytest.MonkeyPatch, config: OrphanetDataConfig) -> tuple[int, dict]:
    monkeypatch.setattr(settings, "data", config)
    response = TestClient(create_app(), raise_server_exceptions=False).get("/health")
    return response.status_code, response.json()


def test_health_publishes_the_release_identity_when_expected_equals_actual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact fragment the fleet release gate and the controller parse."""
    root = _materialize(tmp_path / "data")

    status, body = _health(monkeypatch, _pinned(root))

    assert status == 200
    assert body["data_available"] is True
    identity = body["release_identity"]
    assert identity["schema_version"] == 1
    pair = identity["data_identity"]
    assert set(pair) == {"expected", "actual"}
    assert set(pair["expected"]) == {"release_tag", "digest"}
    assert pair["actual"] == pair["expected"]
    assert pair["actual"] == {"release_tag": RELEASE_TAG, "digest": f"sha256:{BUNDLE_SHA256}"}


def test_health_is_not_healthy_when_the_materialized_release_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volume holding some other release must never be served as if it were this one."""
    other = "d7408be62d055700901e635c1582c3ccdf5245e87b88f53c90f8fbdb2f284a53"
    root = _materialize(tmp_path / "data", bundle_sha256=other)

    status, body = _health(monkeypatch, _pinned(root))

    assert status == 503
    assert body["data_available"] is False
    assert "release_identity" not in body


def test_health_stays_a_liveness_probe_without_a_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unpinned development must not start failing its own health check."""
    root = tmp_path / "data"
    _database(root)

    status, body = _health(monkeypatch, OrphanetDataConfig(data_dir=root, auto_bootstrap=False))

    assert status == 200
    assert body["status"] == "ok"
    assert body["data_available"] is True
    assert "release_identity" not in body


# ------------------------------------------------------------------------------ probe


def test_probe_reports_exactly_the_contract_keys(tmp_path: Path) -> None:
    """`record_count` counts disorders; the hash is over the canonical first key."""
    path = _database(tmp_path / "data")

    payload = probe(path)

    assert set(payload) == {"data_schema_version", "record_count", "query_result_sha256"}
    assert payload["data_schema_version"] == "1"
    assert payload["record_count"] == 3
    # sha256("10"): the lexically first orpha_code in the fixture.
    assert payload["query_result_sha256"] == (
        "4a44dc15364204a80fe80e9039455cc1608281820fe2b24f1e5233ade6af1dd5"
    )


def test_probe_is_deterministic_and_leaves_the_store_untouched(tmp_path: Path) -> None:
    """Observation must not be a write; the controller runs this against live data."""
    path = _database(tmp_path / "data")
    before = sorted((entry.name, entry.stat().st_size) for entry in path.parent.iterdir())

    assert probe(path) == probe(path)
    assert sorted((entry.name, entry.stat().st_size) for entry in path.parent.iterdir()) == before


def test_probe_refuses_a_missing_store(tmp_path: Path) -> None:
    """A missing index is an error, never an empty-looking success."""
    with pytest.raises(DataProbeError):
        probe(tmp_path / "absent.sqlite")


def test_probe_module_prints_one_json_object(tmp_path: Path) -> None:
    """`python -m orphanet_link.data_probe` is the exact controller command."""
    root = tmp_path / "data"
    _database(root)
    environment = {
        "PATH": "/usr/bin:/bin",
        "ORPHANET_LINK_DATA__DATA_DIR": str(root),
        "ORPHANET_LINK_DATA__AUTO_BOOTSTRAP": "false",
    }

    completed = subprocess.run(
        [sys.executable, "-m", "orphanet_link.data_probe"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
    )

    payload = json.loads(completed.stdout)
    assert set(payload) == {"data_schema_version", "record_count", "query_result_sha256"}
    assert completed.stdout.count("\n") == 1


def test_identity_manifest_is_written_beside_the_database(tmp_path: Path) -> None:
    """The manifest lives in the data root, so a candidate volume carries its own proof."""
    root = _materialize(tmp_path / "data")

    manifest = json.loads((root / IDENTITY_FILENAME).read_text(encoding="utf-8"))

    assert set(manifest) == {"schema_version", "release_tag", "bundle_sha256", "database"}
    assert manifest["database"]["path"] == DB_FILENAME


def test_probe_main_prints_the_payload_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The in-process path of the controller command, without a subprocess."""
    root = tmp_path / "data"
    _database(root)
    monkeypatch.setattr(settings, "data", OrphanetDataConfig(data_dir=root))

    assert data_probe_main() == 0

    assert json.loads(capsys.readouterr().out)["record_count"] == 3


def test_probe_main_fails_loudly_on_an_absent_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-zero status, and nothing on stdout that could be parsed as an observation."""
    monkeypatch.setattr(settings, "data", OrphanetDataConfig(data_dir=tmp_path / "absent"))

    assert data_probe_main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "data probe failed" in captured.err


def test_resolver_records_the_identity_only_for_a_pinned_release(tmp_path: Path) -> None:
    """An unpinned materialization must actively drop a manifest an earlier pin left."""
    root = tmp_path / "data"
    _database(root)
    pinned = _pinned(root)

    _record_identity(pinned, BUNDLE_SHA256)
    assert (root / IDENTITY_FILENAME).is_file()

    _record_identity(OrphanetDataConfig(data_dir=root), BUNDLE_SHA256)
    assert not (root / IDENTITY_FILENAME).exists()


def test_resolver_rejects_a_store_whose_identity_is_not_the_configured_pin(
    tmp_path: Path,
) -> None:
    """A volume holding another release must not short-circuit `ensure_database`."""
    other = "d7408be62d055700901e635c1582c3ccdf5245e87b88f53c90f8fbdb2f284a53"
    root = _materialize(tmp_path / "data", bundle_sha256=other)

    assert _db_is_valid(_pinned(root)) is False
    assert _db_is_valid(_pinned(root, bundle_sha256=other)) is True
