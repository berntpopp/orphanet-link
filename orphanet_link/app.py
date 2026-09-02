"""FastAPI host for orphanet-link (thin: health + service info + data bootstrap)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orphanet_link import __version__
from orphanet_link.buildinfo import build_info
from orphanet_link.config import settings
from orphanet_link.logging_config import configure_logging
from orphanet_link.runtime_data_identity import (
    RuntimeDataIdentityError,
    verify_runtime_identity,
)
from orphanet_link.services.refresh import (
    bootstrap_data,
    start_refresh_scheduler,
    stop_refresh_scheduler,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from orphanet_link.config import OrphanetDataConfig

#: Caller-visible reason for a data-identity failure. Fixed and detail-free: the
#: actionable detail is a path and a digest, and /health is unauthenticated.
DATA_UNAVAILABLE_REASON = "the configured data release is not materialized"


def _data_readiness(config: OrphanetDataConfig) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(data_available, release_identity)`` for the materialized store.

    Unpinned (development, local builds): there is no release identity to prove, so
    availability is the presence of the index and ``release_identity`` is absent.
    Pinned (both production overlays): the identity manifest written by the init
    sidecar is re-verified against the database bytes on every call, and anything but
    an exact match to the configured pair is reported as unavailable.
    """
    expected = config.expected_data_identity()
    if expected is None:
        return config.db_path.is_file(), None
    try:
        actual = verify_runtime_identity(config.data_dir, database=config.db_filename)
    except (OSError, RuntimeDataIdentityError):
        return False, None
    if actual != expected:
        return False, None
    return True, {
        "schema_version": 1,
        "data_identity": {"expected": expected, "actual": actual},
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Bootstrap the Orphanet index and (optionally) start the refresh scheduler."""
    logger = configure_logging()
    logger.info("orphanet-link starting", host=settings.host, port=settings.port)
    await bootstrap_data(settings.data, logger)
    refresh_task = start_refresh_scheduler(settings.data, logger)
    try:
        yield
    finally:
        await stop_refresh_scheduler(refresh_task)
        logger.info("orphanet-link shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="orphanet-link",
        description="MCP/API server grounding disease work in the Orphanet rare disease database.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # This backend holds no cookies/session/auth, so CORS credentials are
    # meaningless and a footgun: `allow_credentials=True` combined with a
    # wildcard origin would be a CSRF/credential-leak vector. Keep credentials
    # off and fail closed if a wildcard origin is ever paired with credentials.
    allow_credentials = False
    origins = settings.cors_origins
    if allow_credentials and "*" in origins:
        raise RuntimeError(
            "Insecure CORS: allow_credentials=True cannot be combined with a "
            "wildcard '*' origin on an unauthenticated backend."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> Any:
        """Readiness probe: build provenance plus the proven runtime data identity.

        A pinned deployment that cannot prove its configured data release is NOT
        healthy -- it answers 503 with ``data_available: false`` rather than serving
        whatever happens to be on the volume.
        """
        payload: dict[str, Any] = {
            "status": "ok",
            "service": "orphanet-link",
            "transport": "streamable-http-stateless",
            **build_info(),
        }
        available, release_identity = _data_readiness(settings.data)
        payload["data_available"] = available
        if release_identity is not None:
            payload["release_identity"] = release_identity
            return payload
        if settings.data.expected_data_identity() is None:
            return payload
        payload["status"] = "degraded"
        payload["reason"] = DATA_UNAVAILABLE_REASON
        return JSONResponse(payload, status_code=503)

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service information."""
        return {
            "name": "orphanet-link",
            "version": __version__,
            "data_source": "Orphanet scientific knowledge files (Orphadata) -> local SQLite index",
            "mcp_endpoint": settings.mcp_path,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
