# AGENTS.md — orphanet-link

Guidance for agents and contributors working in this repository.

## What this is

`orphanet-link` is an MCP + REST server that grounds rare-disease queries in
Orphanet's scientific knowledge files (Orphadata). It builds a local SQLite/FTS5
index from the eight English Orphadata XML products and serves 19 read-only tools
for disease lookup, gene and HPO associations, epidemiology, natural history,
functional consequences, classification hierarchy, and cross-ontology mapping.
It mirrors the sibling `mondo-link` stack/architecture and slots into
`genefoundry-router` under the `orphanet` namespace.

---

## Two planes (non-negotiable boundary)

- **Data plane** — `config.py`, `constants.py`, `identifiers.py`, `exceptions.py`,
  `logging_config.py`, `buildinfo.py`, `ingest/`, `data/`, `services/`.
  Downloads the Orphadata XML files (conditional GET with ETag/Last-Modified),
  atomically builds the SQLite index, and **returns plain Python dicts**. It
  raises typed exceptions from `orphanet_link.exceptions`; it **never builds
  error envelopes** and never imports from `orphanet_link.mcp`.

- **MCP plane** — `mcp/`. Domain-agnostic scaffolding copied and adapted from
  `mondo-link`. `run_mcp_tool` (in `mcp/envelope.py`) owns `success` / `_meta`
  and converts exceptions into **returned** structured errors (never raised to the
  client). Tool modules under `mcp/tools/` call service methods and attach
  `_meta.next_commands`; they do not touch SQLite or raise domain exceptions.

The boundary is enforced structurally: the data plane has no knowledge of MCP
types; the MCP plane has no knowledge of SQL or XML.

---

## The eight Orphadata products and where each is parsed

| Product | Orphadata file | Parser module | Tables populated |
|---|---|---|---|
| 1 | `en_product1.xml` | `ingest/parsers/product1.py` | `disorder`, `disorder_synonym`, `disorder_lookup`, `disorder_fts`, `xref` |
| 3 | `en_product3_<id>.xml` (~33) | `ingest/parsers/product3.py` | `classification_edge`, `classification_closure`, `specialty` |
| 4 | `en_product4.xml` | `ingest/parsers/product4.py` | `phenotype` |
| 6 | `en_product6.xml` | `ingest/parsers/product6.py` | `gene`, `disorder_gene` |
| 7 | `en_product7.xml` | `ingest/parsers/product7.py` | `linearisation` |
| 8 (funct) | `en_funct_consequences.xml` | `ingest/parsers/funct.py` | `disability` |
| 9 prev | `en_product9_prev.xml` | `ingest/parsers/product9_prev.py` | `prevalence` |
| 9 ages | `en_product9_ages.xml` | `ingest/parsers/product9_ages.py` | `age_of_onset`, `inheritance` |

Product-3 specialty IDs are non-sequential and not derivable from a fixed
pattern. They are enumerated once via Playwright (`ingest/specialties.py`) and
committed as a cached list; routine builds need no browser. The `--refresh-
specialties` flag re-scrapes when the list needs updating.

Each parser uses `lxml.iterparse` streaming and clears processed elements to
stay memory-bounded. The `<JDBOR date= version=>` header is parsed once per file
for the release stamp stored in the `meta` table.

---

## Artifact pipeline

### CI: `.github/workflows/build-data.yml`

- **Triggers:** weekly schedule (catches bi-annual Orphanet releases within a
  week), `workflow_dispatch`, and a `push` to `main` touching
  `orphanet_link/ingest/**`. The branch filter is load-bearing: GitHub ignores
  `paths:` for tag pushes, so without it every `vX.Y.Z` tag ran the full data
  build — which the `main`-only publisher could never accept.
- **Steps:** checkout → `uv sync` → `uv run orphanet-link-data build` →
  read `meta.orphanet_version` → compute tag `data-<version>` → if a Release for
  that tag already exists, exit (idempotent) → gzip the DB → write `.sha256` and
  `manifest.json` → create the GitHub Release and upload assets via
  `softprops/action-gh-release`.

### Runtime: `services/data_resolver.py`

On server start (`auto_bootstrap=True`, default), the resolver:

1. If `DATA__PREFER_PREBUILT=true` (default): fetch the latest `data-*` GitHub
   Release asset (`orphanet.sqlite.gz`) → verify sha256 → decompress to
   `data_dir` → validate `meta.schema_version` compatibility.
2. On any failure (offline, missing asset, schema mismatch): fall back to a full
   local build (downloader + parsers + builder).

The artifact tag is `data-<JDBOR version>`; `schema_version` is stamped in
`meta` and checked on load. An incompatible prebuilt DB triggers a local rebuild
rather than a crash.

---

## Invariants

- Services return plain dicts; the MCP envelope owns `success`/`_meta` and
  returns structured errors. **7-code error taxonomy**: `invalid_input`,
  `not_found`, `ambiguous_query`, `data_unavailable`, `rate_limited`,
  `upstream_unavailable`, `internal_error`.
- Every `compact` (default) or richer response carries `_meta.next_commands`
  (ready-to-call follow-ups). `minimal` is the explicit opt-out and returns only
  `_meta = {tool, request_id}`. `_meta` verbosity is tiered by `response_mode`
  (`_shape_meta`): `compact` adds `next_commands` + `capabilities_version`;
  `standard`/`full` also add `elapsed_ms`.
- Every tool declares `output_schema` + `READ_ONLY_OPEN_WORLD` annotations.
  Every tool's first description sentence is a discovery summary ending with
  `Signature: tool_name(args...)`.
- **Every tool's real output (success + error, all response modes) must validate
  against its own `output_schema`** — enforced by
  `tests/unit/test_output_schemas.py`. Grouped-by-prefix payloads (`xrefs`,
  `mappings`) are objects keyed by prefix, not arrays; declare them as objects or
  the envelope leaks a raw validation error.
- `response_mode` is one of `minimal | compact | standard | full`. List tools
  carry a pagination block (`total`/`returned`/`limit`/`offset`/`truncated`/
  `next_offset`); when truncated, `_meta.next_commands` offers a forward-page
  step.
- `compact`+ `_meta` echoes `capabilities_version` (SHA-256 hash of the
  discovery contract with volatile keys excluded, cached per Orphanet release) so
  warm clients can skip re-fetching `get_server_capabilities`.
- Keep `mcp/capabilities.py::TOOLS` in sync with the registered tool set.
  `tests/unit/test_tool_names.py` enforces this.
- Identifiers are normalised in `identifiers.py` (ORPHA CURIEs: `ORPHA:N` or
  bare integer; external CURIEs case-folded).
- `structlog` logs to **stderr only** — stdout is reserved for the stdio MCP
  protocol. Never `print` to stdout outside the CLI entrypoint.

---

## Token budget (response_mode × per-call weight)

`response_mode` and the `orphanet_version` policy are the two knobs that set
per-call token cost. Per-call weight, lightest → heaviest:

| Mode | Body | `_meta` keys | Body `orphanet_version` |
|---|---|---|---|
| `minimal` | identity anchors only | `tool, request_id, source, data_version` | dropped |
| `compact` (default) | null/empty dropped recursively; search hits get a snippet | `+ next_commands, capabilities_version` | dropped (use `_meta.data_version`) |
| `standard` | full record | `+ elapsed_ms` | present |
| `full` | full record | `+ elapsed_ms` | present |

The verbose human-readable `orphanet_version` string is shipped only in
`standard`/`full`; in the lean modes the short `_meta.data_version` hash grounds
the call (the envelope trims the body string — discovery tools opt out via
`McpErrorContext(keep_version=True)` because that string is their product).

**Full-entity in one call:** `get_disease(term,
include=['genes','phenotypes','prevalence','disability'])` composes the
association sections into a single record, collapsing the per-section fan-out
(~34% fewer tokens than 4 separate calls on the fixture disorder; the saving
grows with call count). Prefer it over a fan-out when you need the whole entity.

## Determinism & ordering contract

Every list/closure tool returns rows in a **stable, reproducible order**, enforced
by an explicit SQL `ORDER BY` and locked by regression tests
(`test_determinism.py` run-to-run equality + cross-page no-overlap;
`test_boundaries.py` golden forward-walk). The order per surface:

| Surface | Primary sort | Tiebreak |
|---|---|---|
| `search_diseases` | FTS `bm25` relevance (best first) | **ORPHAcode ascending** (enforced via `CAST(orpha_code AS INTEGER)`) — equal-score ties are a contract, not row luck |
| `get_disease_ancestors` / `_descendants` | disorder name (alphabetical) | classification-only nodes have no disorder row (null name) and retain a deterministic build order |
| `find_diseases_by_gene` / `_by_phenotype`, `resolve_xref` | disorder name | deterministic build order |
| `get_disease_genes` | `gene_symbol` | — |
| `get_disease_phenotypes` | `hpo_id` | — |
| `get_disease_prevalence` | `prevalence_type` | — |
| `map_cross_ontology` / `xrefs` | mapping-relation rank, then source, then `object_id` | — |

Forward pagination preserves this total order, so a row never appears on two pages
and none is skipped (the `page_fields` invariant, property-tested in
`test_pagination_invariants.py`). When changing an `ORDER BY`, update the
determinism/snapshot tests deliberately.

## Line budget

Every source file must stay at or below **500 lines**. The budget is enforced by
`scripts/check_file_size.py`, which is run as `make lint-loc` in CI. Split by
responsibility, not by layer, when approaching the limit.

---

## Development commands

```bash
make install        # uv sync --group dev
make format         # ruff format
make lint           # ruff check
make typecheck      # mypy --strict
make test           # pytest (unit only)
make test-integration  # live Orphadata / GitHub Release tests
make test-cov       # pytest with coverage report
make ci-local       # the full gate (below)
make help           # every target, self-documenting
```

Data (`make data-fetch` / `data` / `data-status` / `data-refresh`), server (`make dev`,
`make mcp-serve`) and Docker (`make docker-*`) targets are documented in
`docs/data.md` and `docs/deployment.md`.

## CI gates (`make ci-local`)

```
format-check      ruff format --check
lint-ci           ruff check  (GitHub-Actions output)
lint-loc          scripts/check_file_size.py  (hard cap: ≤500 lines/file)
lint-readme       scripts/check_readme.py  (GeneFoundry README Standard v1)
typecheck         mypy --strict
check-action-pins scripts/check_github_action_pins.py  (full 40-char SHAs)
test-fast         pytest -n auto (unit only), coverage fail_under = 80
```

All gates must be green before merge. After a redeploy, also run:

```bash
make verify-deploy URL=<server>/health
```

This pipes the live `/health` payload into `scripts/check_deployed_freshness.py`
and exits non-zero unless the build `git_sha` matches local HEAD — the guard
against a green local tree whose fixes never reached the running container.

---

## Fleet Deploy Contract

`docker/docker-compose.npm.yml` is the file the fleet controller
(`strato_v6_docker_npm`) renders with `docker compose config --format json`,
projects, and validates before it will author a deployment record. Both
services there — the run-once `orphanet-data-init` sidecar and the long-running
`orphanet_link` app — declare `user: "999:999"` numerically: this image's real
uid:gid (`docker/Dockerfile`: `useradd --system --gid app`), never copied from a
sibling repo, since the fleet is not uniform on uid. `user` must **not** appear
on the application service of the Compose files listed in
`container-release.json`'s `service.compose_files`
(`docker/docker-compose.yml`, `docker/docker-compose.prod.yml`) — the shared
release gate forbids it there, the opposite of what the deployment controller
requires. `tests/unit/test_production_init_sidecar.py`
(`test_npm_deploy_uses_the_same_init_sidecar_boundary`) guards the npm
overlay's init-sidecar shape (it does not itself assert `user`/`cpus`, unlike
gtex-link's dedicated projection-contract test).

As of `strato_v6_docker_npm` PR #41, the controller's projection relaxed:
`user` and `volumes` are optional-but-validated (the runtime observer proves
the effective uid from `/proc` independently), and `cpus` limits accept a
finite positive float. This repo's integer `cpus: 1` on the init sidecar (it
was `"0.5"` before the fleet-contract fix) predates that relaxation and is no
longer strictly required by the controller — kept as-is; do not change the
overlay.

### Runtime data identity (`runtime-v1`)

`container-release.json` declares `"data_identity_contract": "runtime-v1"`. Three
things implement it and they must stay consistent:

1. `orphanet_link/runtime_data_identity.py` — builds and verifies
   `data-identity.json` (`{schema_version, release_tag, bundle_sha256, database:
   {path, size_bytes, sha256}}`) in the data root. `verify_runtime_identity()`
   **rehashes the database file** and only then returns `{release_tag, digest}`,
   where `digest` is `sha256:<compressed bundle sha256>` — the same number
   `container-release.json` declares as `data.digest` and the overlays inject as
   `ORPHANET_LINK_DATA__BUNDLE_EXPECTED_SHA256`. One number, three places.
2. `services/data_resolver.py` — `fetch_prebuilt` writes that manifest after
   materializing a pinned bundle, and drops it on an unpinned fetch or a local build.
   `_db_is_valid` re-verifies it, so a volume holding some other release cannot
   short-circuit the resolver.
3. `app.py::/health` — publishes `data_available` and, when pinned,
   `release_identity: {schema_version: 1, data_identity: {expected, actual}}` with
   both sides keyed exactly `{release_tag, digest}`. Mismatch → **503**,
   `data_available: false`, no `release_identity`. Unpinned (`release_tag: latest`,
   no declared digest) → 200 liveness only. `status` stays `"ok"` on 200 —
   `tests/conformance/test_health_transport.py` pins that literal.

`python -m orphanet_link.data_probe` is the controller's read-only semantic probe:
one JSON object, exactly `{data_schema_version, record_count, query_result_sha256}`,
opened `mode=ro&immutable=1`, no network, no writes, non-root. It is the one
deliberate exception to "no `print` to stdout except the Typer CLI entrypoint" —
its stdout **is** a machine contract. Counting entity: `disorder`; canonical key:
`orpha_code`.

The smoke stack in the central release workflow runs `docker/docker-compose.yml`,
where the application bootstraps its own data, so the pin reaches it through
`smoke_environment` in `container-release.json`. Without those two assignments the
release gate would compare the declared identity against whatever `latest` resolved
to, and fail — burning a version.

`data.schema_compatibility` is **not** set: `genefoundry-router` v0.8.5's
`ExternalReferenceData` model (`release/models.py`) is `extra="forbid"` and has no
such field, so declaring it makes every `container_release.py` command reject the
file with `invalid_evidence`. The manifest field the fleet controller reads
(`data_requirements.schema_compatibility`) is fed from `.data.schema_compatibility`
by `_container-release.yml`, so it stays `[]` until the router model gains the
field. Add it (value `["1"]`, the version `data_probe` reports) in the same change
that bumps the workflow pin past that fix.

The npm overlay's data volume is named
`${ORPHANET_DATA_VOLUME:-orphanet-link-npm_orphanet-data}` — selectable so the
controller can activate a candidate volume, defaulting to the volume live on the
server today. The app addresses data by explicit version directory
(`/data/<release tag>`), never a `latest` symlink.

Guards: `tests/unit/test_runtime_data_identity.py` (identity equal/unequal, probe
shape and determinism) and `tests/unit/test_production_init_sidecar.py`
(`test_release_manifest_adopts_the_runtime_data_identity_contract`,
`test_deployed_overlay_data_volume_is_selectable_and_defaults_to_the_live_volume`).

CITATION.cff is generated (regenerated by `genefoundry-router` from
`fleet-metadata.yaml` + this repo's `pyproject.toml`) — never hand-edit it.
`version:` tracks `pyproject.toml`/the newest CHANGELOG heading; `date-released`
is pinned to `'2026-08-31'` and must **not** be bumped on a routine version
release — `tests/unit/test_version_single_source.py`
(`test_citation_matches_the_unreleased_application_version`) enforces the
pinned literal (see commit `4542431`, which reverted a hand-edit that moved it
to match a version bump).

Release checklist this repo enforces: bump `pyproject.toml`, `uv lock`, add a
`CHANGELOG.md` heading `## [x.y.z] - YYYY-MM-DD`, sync CITATION.cff `version:`
(leave `date-released` at `'2026-08-31'`), tag `vx.y.z`, then approve the
`release` environment gate via
`gh api repos/berntpopp/orphanet-link/actions/runs/<id>/pending_deployments`
(may need approving twice; `status: waiting` on a pending deployment is the
gate to look for).

## Definition of done

A piece of work is done when ALL of the following are true:

- [ ] `make ci-local` is green (all five gates above)
- [ ] Every new or changed tool has `output_schema` + `READ_ONLY_OPEN_WORLD`
- [ ] Every new or changed tool's real output validates against its `output_schema`
      across all `response_mode` values (checked by `test_output_schemas.py`)
- [ ] `mcp/capabilities.py::TOOLS` lists every registered tool (checked by
      `test_tool_names.py`)
- [ ] The README `## Tools` table lists every registered tool (checked by
      `test_readme_tools.py`); the README stays within the GeneFoundry README
      Standard v1 (`make lint-readme`) — move detail into `docs/`, never delete it
- [ ] New parsers use `lxml.iterparse` + `clear()` and are covered by a fixture
      XML sample in `tests/fixtures/`
- [ ] No new file exceeds 500 lines (`lint-loc`)
- [ ] The data plane does not import from `orphanet_link.mcp`; the MCP plane does
      not import from `orphanet_link.ingest` or touch SQLite directly
- [ ] Structured errors are **returned** from `run_mcp_tool`, never raised to the
      client
- [ ] `structlog` only; no `print` to stdout except the Typer CLI entrypoint

---

## Conventions

- Python 3.12+, `uv`, hatchling. Add deps via `pyproject.toml`, then `uv lock`.
- Ruff: line length 100, Google-style docstrings.
- TDD: write the failing test first. Keep unit tests self-contained; build a
  fixture SQLite from `tests/fixtures/` mini-XML samples.
- Frozen contracts: `mcp/` scaffolding, `ingest/schema.sql`, and the
  `OrphanetService` / `OrphanetRepository` method signatures are the seams other
  modules code against — change them deliberately and update tests accordingly.
- `xref` mapping-relation values (`E`, `NTBT`, `BTNT`, `ND`, `W`) must be stored
  verbatim; never flatten or lose `icd_relation` or `validation_status`.
- Gene association status (`Assessed` / `Not yet assessed`) and source PMIDs
  must be stored and returned verbatim.
- Prevalence is multi-valued per disorder (multiple types, geographies, statuses).
  Never aggregate or deduplicate prevalence rows.
- `count` in any payload is the number of **leaf rows**, not the number of groups.
  In `map_cross_ontology` it counts individual mapping targets across all source
  groups (so 2 source groups with 3 targets total reports `count: 3`); in
  `get_disease_genes` it counts gene rows. Document this in the docstring of any
  new grouped-payload tool.
- `get_disease_disability` data coverage is partial: a disorder with no Orphadata
  functional-consequence annotation returns `count: 0` with `coverage: "none"`
  (a valid empty result, never an error); annotated disorders return
  `coverage: "present"`.
- Batch items each carry a stable `index` (input position). A per-item failure with
  `ambiguous_query` (or a suggestion-bearing `not_found`) carries `candidates[]` so
  it is as self-recoverable as the single-call equivalent; candidate count is tiered
  by `response_mode`. A batch over `MAX_BATCH_ITEMS` is rejected with `invalid_input`
  (logged), never silently truncated.

---

## Package layout

```
orphanet_link/
  config.py           # pydantic-settings; env prefix ORPHANET_LINK_; nested __
  constants.py        # SCHEMA_VERSION, XREF prefixes, citation/license strings
  identifiers.py      # ORPHA / OMIM / ICD / HPO / HGNC CURIE normalisation
  exceptions.py       # typed exception hierarchy
  logging_config.py   # structlog -> stderr
  buildinfo.py        # git sha / built_at provenance
  ingest/
    downloader.py     # conditional GET (ETag/Last-Modified); 64 KiB streaming
    specialties.py    # product-3 specialty ID cache + Playwright refresh
    parsers/          # one module per product (lxml.iterparse)
    builder.py        # lock -> mkstemp -> schema -> batch-load -> FTS optimize -> atomic swap
    schema.sql        # DDL (all tables, indexes, FTS5 virtual table)
    schema.py         # schema_version constant + load helper
    lock.py           # fcntl cross-process build lock
    cli.py            # Typer: build / refresh / status  (console script: orphanet-link-data)
  data/
    repository.py     # read-only raw parameterised SQL; FTS sanitisation; schema-version check
  services/
    orphanet_service.py  # singleton facade
    resolution.py        # resolve_disease logic
    shaping.py           # response shaping per response_mode
    pagination.py        # pagination helpers
    refresh.py           # in-process conditional refresh scheduler
    data_resolver.py     # prebuilt-download-or-local-build bootstrap
  mcp/
    envelope.py          # run_mcp_tool; success/_meta/error envelope; error taxonomy
    capabilities.py      # TOOLS list; get_server_capabilities payload
    annotations.py       # READ_ONLY_OPEN_WORLD
    schemas.py           # output_schema dicts for all 19 tools
    next_commands.py     # _meta.next_commands chainers
    metrics.py           # request/error counts, latency percentiles
    middleware.py        # ArgValidationMiddleware
    arg_help.py          # shared argument description helpers
    resources.py         # MCP resource strings (orphanet:// URIs)
    service_adapters.py  # get_orphanet_service() singleton accessor
    facade.py            # create_orphanet_mcp() — assembles FastMCP instance
    tools/
      _common.py         # Annotated type aliases (QueryStr, TermStr, ResponseMode, ...)
      discovery.py       # get_server_capabilities, get_diagnostics
      diseases.py        # resolve_disease, search_diseases, get_disease
      associations.py    # get_disease_genes, get_disease_phenotypes,
                         # get_disease_prevalence, get_disease_natural_history,
                         # get_disease_disability, find_diseases_by_gene,
                         # find_diseases_by_phenotype
      classification.py  # get_disease_classification, get_disease_ancestors,
                         # get_disease_descendants
      xref.py            # map_cross_ontology, resolve_xref
      batch.py           # resolve_disease_batch, get_disease_batch
server.py                # --transport unified|http|stdio
mcp_server.py            # stdio bootstrap (sets FASTMCP_*/NO_COLOR before import)
scripts/
  check_file_size.py
  check_deployed_freshness.py
  check_github_action_pins.py
  check_readme.py            # fleet-shared README linter; vendored VERBATIM — do not edit
```

Repository docs live in `docs/`: [`data.md`](docs/data.md) (sources, build pipeline,
licensing), [`deployment.md`](docs/deployment.md) (transports, Docker, Host/Origin/CORS,
router integration), [`configuration.md`](docs/configuration.md) (`ORPHANET_LINK_*`), and
[`architecture.md`](docs/architecture.md) (envelope, response modes, resources).
