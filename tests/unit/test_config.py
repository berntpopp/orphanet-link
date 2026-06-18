"""Tests for orphanet_link.config."""

from __future__ import annotations

from orphanet_link.config import ServerSettings


def test_defaults_and_env_prefix(monkeypatch):
    monkeypatch.setenv("ORPHANET_LINK_DATA__BASE_URL", "https://example.test/xml")
    s = ServerSettings()
    # trailing slash is normalized on
    assert s.data.base_url == "https://example.test/xml/"
    assert s.data.prefer_prebuilt is True
    assert s.data.release_repo == "berntpopp/orphanet-link"
    assert s.data.db_path.name == "orphanet.sqlite"


def test_default_base_url():
    s = ServerSettings()
    assert s.data.base_url == "https://www.orphadata.com/data/xml/"
    assert s.transport == "unified"
