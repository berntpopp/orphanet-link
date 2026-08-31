# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

- Verify Orphanet release assets, source identity, schema, and counts before
  treating an existing data tag as idempotent; differing or ambiguous releases
  now fail closed without mutation.
- Bound and authenticate release metadata/assets, reject an inexact remote asset
  inventory, and separate read-only building from the narrowly privileged,
  create-only publisher.

## [0.4.4] - 2026-08-31

### Changed

- Consolidate current runtime/tooling updates, use router container workflows at v0.8.3,
  refresh the pinned Python base image, and make the production server restart persistent.
- README validation now identifies the Git remote, so an isolated Git worktree validates
  the repository badges correctly.
- Upgrade Debian packages during the image build and remove bootstrap `setuptools` from the
  production virtual environment to remediate fixable OpenSSL and packaging-tool findings.

## [0.4.3] - 2026-08-10

### Security

- Refresh runtime dependencies, including `cryptography` 50.0.0, and remove
  unused vulnerable packaging tooling from the production image.

### Changed

- Refresh pinned CI actions and use the released genefoundry-router v0.7.6
  reusable container workflows.

## [0.4.2] - 2026-07-30

Python 3.12 → **3.14** for the shipped container and for the interpreter CI executes.
No runtime behaviour change.

### Changed

- **`docker/Dockerfile` base `python:3.12-slim` → `python:3.14-slim`** (digest
  `cea0e604`, Debian 13.6, CPython 3.14.6) in both the `builder` and `prepared` stages.
  This closes the deferral recorded in 0.4.1. Landed as a migration rather than the bare
  base bump Dependabot proposed (#44, RED), because a bare bump breaks the two things
  below.
- **`container-release.json` `image_allowlist` repointed to `python3.14`.** The two
  `opt/venv/lib/python3.12/site-packages/orphanet_link/data/*` entries are interpreter-
  versioned paths that the router's `_container-ci.yml` feeds to the OCI content
  inspector; after a base bump they name files that no longer exist in the image. All
  four allowlisted paths were verified against the actually-built `production` image,
  whose `/opt/venv/lib` now contains only `python3.14`.
- **CI now executes on the interpreter the image ships**: `ci.yml`'s `python-version`
  and the `.github/actions/setup-uv-python` composite default both move `3.12` → `3.14`.
  This is the substantive half of the migration — a base bump alone would have shipped a
  3.14 runtime that no gate had ever run. `uv sync --frozen` resolves cleanly on 3.14
  from the existing lock; `make ci-local` (mypy --strict included) and `make test-cov`
  are green there.

### Not changed, deliberately

- **`requires-python` stays `>=3.12`**, and with it ruff's `target-version = "py312"`
  and mypy's `python_version = "3.12"`. Moving the floor to `>=3.14` makes
  **Container CI fail**, and the failure is not fixable from this repo: the pinned
  reusable workflow (`berntpopp/genefoundry-router/.github/workflows/_container-ci.yml`
  @`86b11f7e`) sets up **only Python 3.12** and then runs `uv lock --check` in the caller
  repo. `uv lock --check` (uv 0.8.7) refuses to download an interpreter, so it aborts
  with `No interpreter found for Python >=3.14 in managed installations or search path`.
  Picking up a fix would require re-pinning that workflow, which is out of scope here.
  The floor is a packaging lower bound, not a claim about the tested runtime; the tested
  runtime is 3.14 and matches the image. Move the floor (and the ruff/mypy targets, which
  then pull in PEP 758 `except` formatting and `UP043`) once the container standard
  provisions an interpreter satisfying the caller's `requires-python`.
- The README **badge** stays at "Python 3.12+" regardless: that line is a canonical
  string hardcoded in the fleet-vendored `scripts/check_readme.py` (README Standard v1),
  so it can only move fleet-wide from genefoundry-router's copy.

## [0.4.1] - 2026-07-30

Consolidated Dependabot sweep. No runtime behaviour change.

### Fixed

- Qualify new Orphanet data-release tags with the exact `orphanet_date` revision. Orphadata can
  update the dataset while retaining its human version string; the revision suffix prevents a
  newer dataset from colliding with an older immutable tag while preserving fail-closed identity
  verification.
- Correct the immutable `actions/attest-build-provenance` v2.2.0 pin used by the protected data
  publisher so the attestation action resolves before draft creation.
- Discover authenticated drafts through a bounded release inventory and recheck them by exact
  numeric release ID, because GitHub's release-by-tag REST endpoint hides unpublished drafts.

- **`.github/dependabot.yml` watched only `github-actions`.** This repo's Python (uv)
  dependencies, its Docker base image, and its Compose stack had therefore never been
  scanned — which is why every Dependabot PR raised here to date was an Actions bump and
  the lock had drifted unattended. The config now follows the fleet-standard four
  ecosystems (`uv` at `/`, `github-actions` at `/`, `docker` and `docker-compose` at
  `/docker`) on staggered Monday Europe/Berlin schedules.
- **Two CodeQL `py/incomplete-url-substring-sanitization` alerts (high)** in
  `tests/unit/test_parser_product1.py`. Both were URL assertions written as
  `startswith` on a host fragment — `startswith("http://www.orpha.net")` also matches
  `http://www.orpha.net.evil.example/…`. Both now assert the full URL with `==`, which
  additionally proves the parser round-trips the whole attribute verbatim (XML entities
  decoded) rather than merely its prefix.
- **`.github/actions/setup-uv-python` had drifted three majors behind the workflows**
  (`astral-sh/setup-uv` v6.8.0 vs v8.3.2), because Dependabot was not raising PRs against
  the composite action. It is now on v9.0.0 with the exact tag named in its pin comment.

### Changed

- Swept the never-watched uv lock (`uv lock --upgrade`, 30 packages): `fastapi`
  0.137.2 → 0.141.1, `fastmcp` 3.4.4 → 3.4.5, `mcp` 1.28.1 → 1.29.0, `uvicorn`
  0.49.0 → 0.52.0, `typer` 0.26.7 → 0.27.0, `mypy` 2.1.0 → 2.3.0, `pytest`
  9.1.0 → 9.1.1, `ruff` 0.15.18 → 0.16.0, `certifi` 2026.6.17 → 2026.7.22,
  `websockets` 16.0 → 17.0. `pyproject` floors are minimum-supported bounds here, not
  lock pins, and every upgrade stays inside its declared upper cap.
- `[tool.ruff.lint]` now uses `select` instead of `extend-select` with an identical rule
  list. ruff 0.16.0 grew its implicit default rule set from 59 to 413 rules, so
  `extend-select` would have silently enabled ~350 rules this repo never opted into. The
  declared list already supersets ruff's pre-0.16 default (E4/E7/E9 + F), so the enforced
  lint policy is byte-identical — adopting further rule families stays a deliberate
  decision rather than a side effect of a dependency bump.
- Pinned actions: `actions/checkout` 7.0.0 → 7.0.1, `astral-sh/setup-uv` 8.3.2 → 9.0.0,
  `actions/setup-python` 6.3.0 → 7.0.0. Every SHA was verified against the upstream tag
  its comment claims.
- `docker/Dockerfile` base image `python:3.12-slim` digest `423ed6ab` → `57cd7c3a`
  (current `3.12-slim`), picking up the base-OS patches. The tag stays on 3.12: the
  package targets `>=3.12`, CI tests 3.12, and `container-release.json`'s
  `image_allowlist` encodes `python3.12` site-packages paths, so a 3.14 move is a
  deliberate migration rather than a dependency bump.
- `CITATION.cff` regenerated (was stale at 0.3.7).

## [0.4.0] - 2026-07-14

MCP contract hardening ([#28]). The fleet behaviour gate went from **42 failures and 2
UNGATED tools to 0 failures and 0 UNGATED**, and the advertised tool surface fell from
**9,913 to 6,081 tokens**. Every defect below was green in CI: none of them were visible
to a unit-test suite that never spoke MCP to a running server, which is why the gate is
now vendored in and run against the container on every PR.

### Security

- **Production now materializes the pinned external snapshot in a hardened init sidecar
  (issue #23).** `orphanet-data-init` verifies the immutable bundle digest and writes the
  versioned volume before the serving process starts. The application mounts that snapshot
  read-only with auto-bootstrap and in-process refresh disabled; it no longer has production
  egress or data-volume write access.

### Fixed

Follow-up to the [#28] review — a hardened behaviour gate (which now sees array-item enums
and grouped payloads) plus adversarial review found four more instances of the same
classes, and one the audit had missed.

- **HIGH — `map_cross_ontology.prefixes` was a silently-empty filter.** It shipped as a
  bare `list[str]`, so `prefixes=["__bogus__"]` returned `count: 0, success: true` —
  indistinguishable from a disorder with no such cross-references. The earlier gate could
  not see it: it probed only *scalar* filters, and its row-finder ignored the grouped
  `mappings` object. It now declares an item `enum` **and** rejects an unrecognised source
  at runtime (`invalid_input`). Applied as a rule to every optional array filter, which
  also caught **`get_disease.fields`** silently zeroing the payload on an unknown field —
  a fourth instance the audit never reported.
- **MEDIUM — `get_disease.include` advertised any string but accepted only
  genes/phenotypes/prevalence/disability**, so `include=["natural_history"]` was
  schema-valid and failed at runtime (the harmful direction). It is now a closed item
  `enum`, matching the runtime.
- **MEDIUM — `error_code` was not actually constrained.** `McpToolError` passed its code
  through verbatim, so a miswritten raise could put e.g. `outside_contract` on an
  `isError: true` envelope. The code is now typed `ErrorCode` (mypy-checked at the call
  site) **and** re-checked at runtime in `_classify`, which severs anything outside the
  closed enum to `internal`.
- **The false `fields=` parameter was still advertised through discovery.**
  `get_server_capabilities` / `orphanet://capabilities` still told a model
  `map_cross_ontology` accepts `fields=[...]` (it rejects it), and still described
  `minimal` as "keeps only orpha_code + name" — contradicting 0.4.0's central fix. Both
  prose surfaces are corrected, and a test now checks the whole serialised discovery
  payload, not just the decorator description.
- **A rejected array-item value now names the allowed vocabulary.** A closed
  `list[Literal[...]]` puts its enum under `items.enum`, so a bad element
  (`prefixes.0`) was misclassified as an *unknown argument* — "Did you mean `prefixes`?"
  — telling the model to fix the argument that was already right. The arg-validation
  middleware now resolves an indexed `loc` to its base parameter and surfaces the item
  enum: `invalid_input`, *"each item must be one of: OMIM, MONDO, ICD-10, …"*, with the
  values in `allowed_values` — an error a model can self-correct from in one step.

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

- Re-vendored the behaviour conformance gate from genefoundry-router `56db958`
  (`docs/conformance/behaviour.py` blob `c69801687`) and live-validated this
  backend against the current behaviour gate.
- `XREF_SOURCES`, `ERROR_CODES`, the HPO-frequency and include vocabularies are now each
  declared **once** as a `Literal` and derived into their list forms — a bare
  hand-maintained `XREF_PREFIXES` duplicate (a third copy of the same eight strings) is
  aliased away. `test_pagination_invariants` derives the set of paginated tools from the
  registry instead of hardcoding six, so a new list tool cannot ship untested.

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
