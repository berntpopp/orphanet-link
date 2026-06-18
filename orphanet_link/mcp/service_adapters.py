"""Lazily-constructed singleton OrphanetService for MCP tools.

The repository is opened against the already-built SQLite index (the server
lifespan bootstraps it; see ``orphanet_link.app``). If the index is not present yet,
the service is built without a repository -- tools then return ``data_unavailable``.
orphanet-link has no live API, so there is no fallback client.
"""

from __future__ import annotations

import logging

from orphanet_link.config import settings
from orphanet_link.services.orphanet_service import OrphanetService

logger = logging.getLogger(__name__)

_service: OrphanetService | None = None


def _build_service() -> OrphanetService:
    db_path = settings.data.db_path
    if db_path.exists():
        return OrphanetService(db_path=db_path)
    return OrphanetService()


def get_orphanet_service() -> OrphanetService:
    """Return a process-wide :class:`OrphanetService` (built on first use)."""
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def reset_orphanet_service() -> None:
    """Drop the cached service so the next call re-opens the repository."""
    global _service
    _service = None


def set_orphanet_service(service: OrphanetService | None) -> None:
    """Override the singleton (used by tests)."""
    global _service
    _service = service
