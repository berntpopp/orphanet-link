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
  week), `workflow_dispatch`, and `push` touching `orphanet_link/ingest/**`.
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

## Line budget

Every source file must stay at or below **500 lines**. The budget is enforced by
`scripts/check_file_size.py`, which is run as `make lint-loc` in CI. Split by
responsibility, not by layer, when approaching the limit.

---

## CI gates (`make ci-local`)

```
format-check   ruff format --check
lint-ci        ruff check  (GitHub-Actions output)
lint-loc       scripts/check_file_size.py  (hard cap: ≤500 lines/file)
typecheck      mypy --strict
test-fast      pytest -n auto (unit only), coverage fail_under = 80
```

All five gates must be green before merge. After a redeploy, also run:

```bash
make verify-deploy URL=<server>/health
```

This pipes the live `/health` payload into `scripts/check_deployed_freshness.py`
and exits non-zero unless the build `git_sha` matches local HEAD — the guard
against a green local tree whose fixes never reached the running container.

---

## Definition of done

A piece of work is done when ALL of the following are true:

- [ ] `make ci-local` is green (all five gates above)
- [ ] Every new or changed tool has `output_schema` + `READ_ONLY_OPEN_WORLD`
- [ ] Every new or changed tool's real output validates against its `output_schema`
      across all `response_mode` values (checked by `test_output_schemas.py`)
- [ ] `mcp/capabilities.py::TOOLS` lists every registered tool (checked by
      `test_tool_names.py`)
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
```
