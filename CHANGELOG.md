# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-07-14

MCP contract hardening ([#28]). The fleet behaviour gate went from **42 failures and 2
UNGATED tools to 0 failures and 0 UNGATED**, and the advertised tool surface fell from
**9,913 to 6,081 tokens**. Every defect below was green in CI: none of them were visible
to a unit-test suite that never spoke MCP to a running server, which is why the gate is
now vendored in and run against the container on every PR.

### Fixed

- **CRITICAL — `response_mode="minimal"` discarded the entire payload and still reported
  `success: true`.** It kept the identity anchors and nothing else, so
  `get_disease_genes(term="ORPHA:33069", response_mode="minimal")` answered with no
  `genes` and no `count` — byte-identical to a disorder that genuinely has no gene
  associations. Reproduced on six tools (genes, phenotypes, prevalence, natural history,
  classification, ancestors) and latent on every other shaped tool. `minimal` now returns
  every collection with each record narrowed to its stable identifiers, plus `count` —
  which is what Response-Envelope Standard v1 always said it was ("the mandatory envelope
  plus **stable identifiers**"). An unregistered collection is kept WHOLE rather than
  dropped, so the failure mode is now unrepresentable rather than merely fixed.
- **Every error envelope carried `isError: false`.** A returned dict cannot set the MCP
  protocol flag, so a client branching on `isError` — as the spec tells it to — read every
  one of this server's errors as a *successful call*. Error envelopes now ride a
  `ToolResult(is_error=True)`, which is the only shape that carries both the flag and the
  machine-readable envelope (raising sets the flag but nulls `structuredContent`).
- **`get_diagnostics` advertised an `outputSchema` naming six properties the server never
  returns** (`term_count`, `obsolete_count`, `xref_count`, `mapping_count`,
  `data_available`, `built_utc`). `additionalProperties: true` meant it still *validated*,
  so the lie stayed invisible until an agent read `resp["term_count"]` and hit a KeyError.
- **`map_cross_ontology`'s description promised a `fields=['xrefs.OMIM']` parameter that
  the tool rejects**, and named a key (`xrefs`) it does not return (`mappings`). A model
  that followed the description got a hard `invalid_input`. The description is now true;
  a test scans every tool's prose for `arg=` promises its schema does not accept.
- **`search_diseases` amplified junk 2x.** An unbounded `query` was echoed back in the
  payload *and* again in `_meta.next_commands`: a 5,000-character query cost the caller a
  10,405-character response for zero information. Free-text arguments now declare a
  `maxLength`, so an over-long call is rejected (567 chars, value not echoed).

### Changed

- **BREAKING — `error_code` is now the closed Response-Envelope v1 enum**
  (`invalid_input`, `not_found`, `ambiguous_query`, `upstream_unavailable`, `rate_limited`,
  `internal`). Three codes of this server's own invention are folded onto the canon, so a
  client written against the fleet contract finally has a branch for every error it can
  receive:
  `data_unavailable` → `upstream_unavailable` (still retryable, still chains to
  `get_diagnostics`), `limit_exceeded` → `invalid_input` (client-fixable: narrow the
  request), `internal_error` → `internal`.
- **`outputSchema` is no longer advertised** (Tool-Surface Budget Standard v1, B2). It was
  40% of a surface that every client re-sends on every request, for a field the MCP spec
  makes optional and no model reads. `structuredContent` is unaffected — verified against
  the running server. With `dereference_schemas=False`, the surface is **9,913t → 6,081t**;
  no description was shortened (`doc%` stays 100).
- **`get_disease_phenotypes.frequency` is now a declared `enum`** (S4). It was a bare
  string over a closed 6-value vocabulary, so a model had to guess the exact label — and
  the natural guess (`"Frequent"` for `"Frequent (79-30%)"`) is exactly the silently-empty
  filter this standard exists to kill. It now rejects with `invalid_input`.
- **The `term` examples name a disorder that actually has data.** The old example carried
  no functional-consequence annotation, so `get_disease_disability` was gated against an
  empty result; `get_disease_descendants` exampled a leaf disease, which can never *have*
  descendants. Both now example terms that teach the model something true.

### Added

- **`resolve_disease_batch.queries` and `get_disease_batch.terms` carry `examples`** (S2/S3).
  Without them, neither a model nor the behaviour gate could construct a valid call: both
  tools shipped UNGATED — exercised by nobody.
- **The Behaviour Conformance v1 gate is vendored and runs against the container in CI**
  (`tests/conformance/behaviour.py`, byte-identical from `genefoundry-router`). Every probe
  is derived from this server's own advertised schema, so a new tool is gated the day it
  ships and a tool that cannot be probed FAILS rather than passing quietly.

[#28]: https://github.com/berntpopp/orphanet-link/issues/28

## [0.3.7] - 2026-07-14

### Changed

- **The NPM deployment pulls the released image instead of building from source.**
  `docker/docker-compose.npm.yml` carried `build:`, so a deploy rebuilt the image on the
  server even though CI had already published an attested, digest-addressable image to
  GHCR. It now requires `ORPHANET_LINK_IMAGE` pinned to a digest and fails closed when it
  is unset. Nothing else in the overlay changed: `container_name`, the Compose project
  name, the healthcheck (including the long first-boot `start_period`), networks and
  volumes are all preserved, so the deployed topology and the persisted Orphanet SQLite
  database are untouched.

## [0.3.6] - 2026-07-13

### Fixed

- **Signed release evidence now states the data contract this service actually declares.**
  The reusable release workflow hardcoded `--contract data-independent` and a fixed
  `data_requirements: {"mode":"none"}`, so every published manifest claimed the image binds
  to no data at all — while `container-release.json` declares `data-bound` /
  `external-reference` against the immutable Orphanet bundle
  (`data-1.3.42-4.1.8-2025-03-03`,
  `sha256:a8af3fc39cca2acedd12c188cb0e1f907ac320e73d2b965c17ad5a28c5f5fe38`). Because the
  evidence assembler returns early for a data-independent contract, the strongest assertion
  in the chain — that the definition evidence binds to the exact pinned artifact — was
  silently skipped. Re-pinning the container-release standard to
  `86b11f7ed062ed84dfddcbd309e34da88f3dae5b` sources the contract and the exact data
  identity from `container-release.json`, so the manifest states the real binding and the
  assertion runs. The v0.3.5 image and its attestations are sound; only its evidence
  understated the binding, and regenerating that evidence requires this patch re-release.

## [0.3.5] - 2026-07-13

### Fixed

- Re-pin the reusable container CI and container release callers to the
  corrected GeneFoundry router release standard
  (`58d011d9c72efe90337244342fdec703f2b5b4b9`), which repairs seven latent
  defects in the previously pinned revision that prevented the container
  release workflow from completing. Research use only.

### Changed

- Bump `actions/checkout` from v5.0.1 to v7.0.0
  (`9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0`) and `softprops/action-gh-release`
  from v3.0.1 to v3.0.2 (`3d0d9888cb7fd7b750713d6e236d1fcb99157228`) in the
  data-build workflow, keeping both SHA-pinned. Supersedes Dependabot #18 and
  #16.

## [0.3.4] - 2026-07-13

### Added

- Adopt the GeneFoundry router container-release standard with SHA-pinned
  reusable container CI/release callers, digest-only production image
  configuration, code-only Docker context controls, and complete OCI image
  labels.

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
