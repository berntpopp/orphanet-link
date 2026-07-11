# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - 2026-07-11

### Changed (BREAKING)

- Response-Envelope Standard v1.1 untrusted-content fencing: `get_disease`'s
  `definition` and `search_diseases`' `results[*].definition` (standard/full
  response modes) are no longer bare strings. Each is now a typed
  `untrusted_text` object (`kind`, `text`, `provenance.{source,record_id,
  retrieved_at}`, `raw_sha256`) so upstream Orphanet prose is structurally
  typed as data, never confusable with instructions, at the MCP boundary.
  Defense in depth; research use only. Hosts reading the old bare-string
  `definition` field must update to read `definition.text`.

### Security

- Add `orphanet_link/mcp/untrusted_content.py` (the byte-identical PubTator
  v1.1 fence primitive plus a limits helper) and enforce the standard's
  2 MiB/object and 128-objects/8-MiB-total ceilings on every fenced response.

## [0.2.0] - 2026-07-10

### Security

- Enforce exact configurable Host and Origin allowlists across every HTTP
  route, with safe loopback defaults, wildcard rejection, explicit production
  proxy hosts, and native FastMCP protection in depth. FastMCP is upgraded to
  3.4.4 while preserving structured argument-validation error envelopes.

### Changed (BREAKING)

- Host and Origin admission is now default-deny outside the configured
  loopback values. Non-loopback and reverse-proxy deployments must list their
  exact public names in `ORPHANET_LINK_ALLOWED_HOSTS` and browser origins, when
  used, in `ORPHANET_LINK_ALLOWED_ORIGINS`.

## [0.1.4] - 2026-07-10

### Security

- Harden Orphanet XML and prebuilt database acquisition with exact-host
  validated redirects, configurable compressed and expanded limits, streamed
  SHA-256 verification, bounded gzip expansion, schema validation before
  replacement, and atomic preservation of the previous database on failure.

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
