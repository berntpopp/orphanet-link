# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.3] - 2026-07-07

### Security

- Base `docker/docker-compose.yml` now loopback-binds the published host port
  (`127.0.0.1:...`) so copying the dev/local compose to a server never
  publishes the unauthenticated backend on the public IP (Docker otherwise
  binds `0.0.0.0` and bypasses the host firewall). Production still fronts the
  container with the reverse proxy via the prod/npm overlays.
- CORS credentials are now disabled (`allow_credentials=False`) on this
  unauthenticated backend, which holds no cookies/session/auth; the app also
  fails closed if a wildcard origin is ever paired with credentials.
- `get_diagnostics` and the bootstrap/refresh/resolver log lines no longer emit
  the absolute host filesystem path of the SQLite index (an info leak reachable
  by callers through the router); only the DB basename is reported.

### Fixed

- `build_info()` normalizes the Docker `ORPHANET_LINK_GIT_SHA=unknown` sentinel
  to `None`, so `/health`, `serverInfo` build info, and discovery no longer
  surface the misleading literal `"unknown"` git sha.

### Added

- MCP `_meta` now stamps `unsafe_for_clinical_use: True` on every tool response
  (success and error paths alike), at every `response_mode`. Previously the
  research-use disclaimer lived only in the static `get_server_capabilities`
  discovery payload; it is now emitted per-call so every response is
  self-describing, matching the fleet-wide disclaimer standardization decision.

## [0.1.2] - 2026-07-03

### Fixed

- MCP `initialize` now advertises the package version in `serverInfo.version`.
  The `FastMCP(...)` constructor lacked a `version=` argument, so the handshake
  leaked the FastMCP framework version (e.g. `3.4.2`) instead of the
  orphanet-link release. The facade now passes `version=__version__`.

### Changed

- Single-source versioning: the package version now lives **only** in
  `pyproject.toml` `[project].version`. `orphanet_link.__version__` is derived
  from installed metadata via `importlib.metadata.version("orphanet-link")`
  (falling back to `0.0.0` in an uninstalled source checkout) instead of a
  hardcoded string, so `pyproject.toml`, `__version__`, `/health`, build info,
  and MCP `serverInfo.version` can no longer drift apart. A guard test
  (`tests/unit/test_version_single_source.py`) locks the invariant.
