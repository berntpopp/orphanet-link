# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.3] - 2026-07-12

### Security

- Pinned every third-party GitHub Action to an audited full commit SHA, added a
  recursive workflow/composite-action pin check, and configured Dependabot to
  keep GitHub Action updates reviewable. Research use only.

## [0.3.2] - 2026-07-11

### Security

- Guard the FastMCP-core not-found reflection surface (Response-Envelope v1.1
  §Error-message sanitation fast-follow). FastMCP core echoes the caller's OWN
  requested tool name / resource URI / prompt name (with any
  control/zero-width/bidi/NUL code points) back to the caller and to logs BEFORE
  any backend middleware runs. A new `orphanet_link/mcp/notfound_guard.py` closes
  it with fixed, input-free constants: Layer 1 preflights the tool name
  (`get_tool(name) is None` -> fixed name-free `not_found` envelope, `is_error=True`,
  no `_meta.tool` echo); Layer 2 masks any `on_read_resource` failure with a fixed
  URI-free `ResourceError`; Layer 3 a protocol-handler backstop wraps the raw
  CallTool/ReadResource/GetPrompt handlers (covers the unknown-tool return path and
  the unknown-prompt echo); Layer 5 a validation-log scrub filter neutralizes the
  FastMCP/MCP-SDK records ("Tool cache miss for", "Handler called: ...", "Failed to
  validate request") at their source loggers + FastMCP's non-propagating Rich
  handlers so no caller name/URI reaches a log sink at any level. Caller
  self-reflection surface (lower risk than upstream injection); no schema change.
  Research use only.

## [0.3.1] - 2026-07-11

### Security

- Defense-in-depth error-message sanitation (secondary surface on top of the v1.1
  untrusted-text fence). Every caller-visible error/diagnostics string is stripped
  of the ratified control/zero-width/bidi/NUL code points (`sanitize_message` +
  a recursive whole-envelope `sanitize_tree`) so they can never reach the model in
  either `structured_content` or the `TextContent` JSON mirror. Attacker-
  influenceable prose and internal detail are additionally SEVERED to fixed,
  body-free messages at the source: the local SQLite index path and raw sqlite
  `str(exc)` are no longer echoed into MCP error messages or `get_diagnostics`; the
  argument-validation frame maps to a fixed reason with a code-point-stripped field
  name; and the runtime bootstrap artifact-fetch client no longer echoes upstream
  release-metadata / gzip body bytes into `DataUnavailableError` or into
  bootstrap/refresh telemetry logs (only the exception class is logged). Research
  use only.

## [0.3.0] - 2026-07-11

### Changed (BREAKING)

- Response-Envelope Standard v1.1 untrusted-content fencing: every externally
  sourced Orphanet free-text surface is now a typed `untrusted_text` object
  (`kind`, `text`, `provenance.{source,record_id,retrieved_at}`, `raw_sha256`)
  instead of a bare string, so upstream prose is structurally typed as data,
  never confusable with instructions, at the MCP boundary. Fenced fields:
  `get_disease`'s `definition`; `search_diseases`' `results[*].definition`
  (standard/full modes) **and** `results[*].definition_snippet` (compact mode --
  the default and most-used search path); and `get_disease_batch`'s per-record
  `definition`. The two search fields remain mutually exclusive per response
  mode, so a response never duplicates the same prose. Hosts reading the old
  bare-string `definition` / `definition_snippet` fields must update to read the
  `.text` subfield. Defense in depth; research use only.

### Added

- `limit_exceeded` error code: a fenced response that exceeds a v1.1 ceiling
  (object count / per-object bytes / total bytes) now returns an explicit typed
  limit error (recovery `reformulate_input`), never a generic `internal_error` --
  the standard forbids silent omission.

### Security

- Add `orphanet_link/mcp/untrusted_content.py` (the byte-identical PubTator v1.1
  fence primitive plus a limits helper) and apply it at the MCP serialization
  boundary (`orphanet_link/mcp/untrusted_fencing.py`), keeping the data plane free
  of any MCP dependency. Every tool aggregates all the fenced objects it emits
  into ONE limit check so the whole-response ceilings bind (2 MiB/object,
  8 MiB total); the object-count ceiling is each tool's real result cap (search =
  200 hits, batch = 50 records), not the bare 128 default, so a legitimate
  full-size response never raises. Compact search snippets are truncated from the
  RAW upstream prose (tab/LF/CR preserved) before fencing, so `raw_sha256` covers
  the true served bytes.

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
