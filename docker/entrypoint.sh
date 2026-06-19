#!/usr/bin/env bash
# Ensure the Orphanet SQLite database exists before serving.
# On first boot the data resolver tries to fetch a prebuilt DB from the GitHub
# Release and falls back to a local build from the Orphadata XML source files.
# A failure here is non-fatal: the unified lifespan also bootstraps on first
# use, so the server starts regardless.
set -euo pipefail

echo "[entrypoint] Ensuring the Orphanet database exists..."
# Use the production venv's python directly (on PATH); `uv run` would try to
# create a project .venv, which the non-root user cannot write in this image.
if python -c "
from orphanet_link.config import settings
from orphanet_link.services.data_resolver import ensure_database
ensure_database(settings.data)
"; then
    echo "[entrypoint] Orphanet database ready."
else
    echo "[entrypoint] WARN: database bootstrap failed; data bootstrap deferred to app startup."
fi

exec python server.py \
    --transport "${ORPHANET_LINK_TRANSPORT:-unified}" \
    --host "${ORPHANET_LINK_HOST:-0.0.0.0}" \
    --port "${ORPHANET_LINK_PORT:-8000}"
