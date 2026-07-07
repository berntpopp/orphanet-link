"""Startup data bootstrap and optional in-process refresh scheduler.

The in-process scheduler is OFF by default (``config.refresh_enabled=False``).
Orphanet releases are bi-annual; refresh is best driven by the CI artifact
pipeline + an external cron.  ``bootstrap_data`` ensures the database exists
on first start — non-fatal: the server still starts and tools report
``data_unavailable`` until the build lands.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

from orphanet_link.exceptions import DataUnavailableError, DownloadError

if TYPE_CHECKING:
    from orphanet_link.config import OrphanetDataConfig


async def bootstrap_data(config: OrphanetDataConfig, logger: Any) -> None:
    """Ensure the local index exists; runs in a worker thread. Non-fatal.

    Args:
        config: Active data-store configuration.
        logger: structlog (or stdlib logging) logger for status messages.
    """
    from orphanet_link.services.data_resolver import ensure_database

    try:
        path = await asyncio.to_thread(ensure_database, config)
        logger.info("orphanet_data_ready", db_file=path.name)
    except (DataUnavailableError, DownloadError, OSError) as exc:
        logger.warning("orphanet_data_bootstrap_failed", error=str(exc))


async def _refresh_loop(config: OrphanetDataConfig, logger: Any) -> None:
    """Periodically call ensure_database to pick up a freshly published release."""
    from orphanet_link.services.data_resolver import ensure_database

    interval = config.refresh_interval_hours * 3600
    while True:
        jitter = random.uniform(0, config.refresh_jitter_seconds)  # noqa: S311
        await asyncio.sleep(interval + jitter)
        try:
            path = await asyncio.to_thread(ensure_database, config)
            logger.debug("orphanet_data_refresh_checked", db_file=path.name)
        except (DataUnavailableError, DownloadError, OSError) as exc:
            logger.warning("orphanet_data_refresh_failed", error=str(exc))


def start_refresh_scheduler(config: OrphanetDataConfig, logger: Any) -> asyncio.Task[None] | None:
    """Start the optional refresh loop task; return the task or ``None`` if disabled.

    Args:
        config: Active data-store configuration.
        logger: structlog (or stdlib logging) logger.

    Returns:
        The running :class:`asyncio.Task`, or ``None`` when
        ``config.refresh_enabled`` is ``False``.
    """
    if not config.refresh_enabled:
        return None
    logger.info(
        "orphanet_refresh_scheduler_enabled",
        interval_hours=config.refresh_interval_hours,
    )
    return asyncio.create_task(_refresh_loop(config, logger))


async def stop_refresh_scheduler(task: asyncio.Task[None] | None) -> None:
    """Cancel the refresh loop task if it is running.

    Args:
        task: The task returned by :func:`start_refresh_scheduler`, or ``None``.
    """
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
