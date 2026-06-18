"""Session-scoped fixtures for the orphanet-link test suite.

Builds a real tiny SQLite database from the XML fixtures in tests/fixtures/,
then layers an OrphanetRepository, OrphanetService, and a fully-wired FastMCP
facade on top of it so tool tests run against a real (though minimal) index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.data.repository import OrphanetRepository
from orphanet_link.ingest.builder import build_database
from orphanet_link.mcp.facade import create_orphanet_mcp
from orphanet_link.mcp.service_adapters import reset_orphanet_service, set_orphanet_service
from orphanet_link.services.orphanet_service import OrphanetService

FX = Path(__file__).parent / "fixtures"


def _build_db(tmp_path: Path) -> Path:
    cfg = OrphanetDataConfig(data_dir=tmp_path)
    paths = {
        "product1": FX / "en_product1.xml",
        "product4": FX / "en_product4.xml",
        "product6": FX / "en_product6.xml",
        "product7": FX / "en_product7.xml",
        "product9_prev": FX / "en_product9_prev.xml",
        "product9_ages": FX / "en_product9_ages.xml",
        "funct": FX / "en_funct_consequences.xml",
    }
    classification_paths = {"156": FX / "en_product3_156.xml"}
    return build_database(cfg, paths, classification_paths)


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the fixture database once for the entire test session."""
    tmp = tmp_path_factory.mktemp("orphanet_mcp_db")
    return _build_db(tmp)


@pytest.fixture(scope="session")
def repo(db_path: Path) -> OrphanetRepository:
    """Open the fixture database as a read-only repository."""
    r = OrphanetRepository(db_path)
    yield r
    r.close()


@pytest.fixture(scope="session")
def service(repo: OrphanetRepository) -> OrphanetService:
    """Build an OrphanetService injected with the fixture repository."""
    return OrphanetService(repo=repo)


@pytest.fixture(scope="session")
def facade(service: OrphanetService):
    """Create a FastMCP facade wired to the fixture service (no real DB needed)."""
    set_orphanet_service(service)
    mcp = create_orphanet_mcp()
    yield mcp
    reset_orphanet_service()
