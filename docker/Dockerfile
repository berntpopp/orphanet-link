# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for orphanet-link.

# Base image pinned by digest (manifest-list) for byte-reproducible rebuilds —
# Container & Deployment Hardening Standard v1, rule 2. Bump via Renovate/Dependabot.
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    ORPHANET_LINK_HOST=0.0.0.0 \
    ORPHANET_LINK_PORT=8000 \
    ORPHANET_LINK_TRANSPORT=unified \
    ORPHANET_LINK_MCP_PATH=/mcp \
    ORPHANET_LINK_DATA__DATA_DIR=/app/data \
    # The entrypoint bootstraps the database before the server starts.
    # Refresh is owned by the CI artifact pipeline + external cron, so the
    # in-app scheduler stays OFF.
    ORPHANET_LINK_DATA__AUTO_BOOTSTRAP=true \
    ORPHANET_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp/orphanet-link

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp/orphanet-link /app/data && \
    chown -R app:app /tmp/orphanet-link /app/data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./orphanet_link ./orphanet_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN /opt/venv/bin/pip install . --no-deps && chmod +x /usr/local/bin/entrypoint.sh

# Stamp build provenance so get_server_capabilities/_meta can report which build
# answered. Pass at build time, e.g.:
#   docker build --build-arg ORPHANET_LINK_GIT_SHA=$(git rev-parse --short HEAD) \
#                --build-arg ORPHANET_LINK_BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ) .
ARG ORPHANET_LINK_GIT_SHA=unknown
ARG ORPHANET_LINK_BUILT_AT
ENV ORPHANET_LINK_GIT_SHA=${ORPHANET_LINK_GIT_SHA} \
    ORPHANET_LINK_BUILT_AT=${ORPHANET_LINK_BUILT_AT}

USER app

EXPOSE 8000

# The SQLite database lives under ORPHANET_LINK_DATA__DATA_DIR (/app/data).
# Mount a volume there so the database persists across container restarts.
VOLUME ["/app/data"]

# start-period covers the entrypoint's first bootstrap (fetch prebuilt or local build).
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
