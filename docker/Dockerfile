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

# Bootstrap uv from a digest-pinned image (F-19) instead of a floating
# pip-based installer upgrade, which resolved a new installer on every
# rebuild. Bump the tag+digest via Renovate/Dependabot.
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

RUN uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS prepared


# Release identity is supplied by the central container-release workflow.
ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="Orphanet Link" \
      org.opencontainers.image.description="MCP/API server for Orphanet rare-disease research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/orphanet-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/orphanet-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/orphanet-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}" \
    ORPHANET_LINK_GIT_SHA="${VCS_REF}" \
    ORPHANET_LINK_BUILT_AT="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    ORPHANET_LINK_HOST=0.0.0.0 \
    ORPHANET_LINK_PORT=8000 \
    ORPHANET_LINK_TRANSPORT=unified \
    ORPHANET_LINK_MCP_PATH=/mcp \
    ORPHANET_LINK_DATA__DATA_DIR=/data \
    # Local Compose opts in; production uses a hardened init sidecar.
    # Refresh is owned by the CI artifact pipeline + external cron, so the
    # in-app scheduler stays OFF.
    ORPHANET_LINK_DATA__AUTO_BOOTSTRAP=false \
    ORPHANET_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /data && \
    chown -R app:app /data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./orphanet_link ./orphanet_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN /opt/venv/bin/pip install . --no-deps && chmod +x /usr/local/bin/entrypoint.sh

RUN rm -rf /root/.cache/pip \
           /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.* \
    && find / -xdev -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find / -xdev -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
RUN find / -xdev -perm /6000 -exec chmod a-s '{}' + \
    && test -z "$(find / -xdev -perm /6000 -print -quit)"
RUN actual="$(find / -xdev -type f -links +1 -printf '%i %p\n' | sort -k2,2)" \
    && expected="$(printf '%s %s\n%s %s\n' \
         "$(stat -c '%i' /usr/bin/perl)" /usr/bin/perl \
         "$(stat -c '%i' /usr/bin/perl5.40.1)" /usr/bin/perl5.40.1 | sort -k2,2)" \
    && { test "$actual" = "$expected" || { printf 'unexpected hardlinks:\n%s\n' "$actual"; exit 1; }; } \
    && rm -f /usr/bin/perl5.40.1

FROM scratch AS production
COPY --from=prepared / /

ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="Orphanet Link" \
      org.opencontainers.image.description="MCP/API server for Orphanet rare-disease research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/orphanet-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/orphanet-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/orphanet-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}" \
    ORPHANET_LINK_GIT_SHA="${VCS_REF}" \
    ORPHANET_LINK_BUILT_AT="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    ORPHANET_LINK_HOST=0.0.0.0 \
    ORPHANET_LINK_PORT=8000 \
    ORPHANET_LINK_TRANSPORT=unified \
    ORPHANET_LINK_MCP_PATH=/mcp \
    ORPHANET_LINK_DATA__DATA_DIR=/data \
    # Local Compose opts in; production uses a hardened init sidecar.
    # Refresh is owned by the CI artifact pipeline + external cron, so the
    # in-app scheduler stays OFF.
    ORPHANET_LINK_DATA__AUTO_BOOTSTRAP=false \
    ORPHANET_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp
WORKDIR /home/app/web

USER app

EXPOSE 8000

# The SQLite database lives under ORPHANET_LINK_DATA__DATA_DIR (/data).
# Mount a volume there so the database persists across container restarts.
VOLUME ["/data"]

# Local Compose may bootstrap before health is ready; production uses an init sidecar.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
