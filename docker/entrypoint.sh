#!/usr/bin/env bash
# The local/dev compose enables an in-process bootstrap. Production disables it
# and supplies the SQLite snapshot through the hardened init sidecar instead.
set -euo pipefail

if python -c "
from orphanet_link.config import settings
raise SystemExit(not settings.data.auto_bootstrap)
"; then
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
else
    echo "[entrypoint] Automatic database bootstrap disabled."
fi

exec python server.py \
    --transport "${ORPHANET_LINK_TRANSPORT:-unified}" \
    --host "${ORPHANET_LINK_HOST:-0.0.0.0}" \
    --port "${ORPHANET_LINK_PORT:-8000}"
