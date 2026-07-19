# orphanet-link — Design Spec

**Date:** 2026-06-18
**Status:** Approved design, pre-implementation

> Historical record — this specification records the approved design as of its date. Current
> behavior is defined by implemented code, standards, release evidence, and tests.

**Author:** drafted with Claude (MCP fleet engineering)

## 1. Purpose & summary

`orphanet-link` is a read-only Model Context Protocol (MCP) server that grounds
rare-disease questions in **Orphanet's scientific knowledge files** (Orphadata).
It is backed by a locally-built, read-only **SQLite + FTS5** database parsed from
the English Orphadata XML products. The database is **built in CI and published
to GitHub Releases as a versioned artifact**; the server downloads the prebuilt
database at runtime for fast cold-start and falls back to building locally if the
artifact is unavailable.

The server is a sibling in the GeneFoundry "-link" fleet. It follows the same
two-plane architecture and conventions as `mondo-link` and is designed to slot
into `genefoundry-router` under the `orphanet` namespace.

## 2. Goals

- Expose Orphanet rare-disease knowledge — nomenclature, cross-references,
  classifications, gene associations, HPO phenotypes, epidemiology (prevalence),
  and natural history (age of onset + inheritance) — through a clean MCP tool
  surface.
- Build a performant, offline-queryable SQLite/FTS5 database from the canonical
  Orphadata English XML files.
- Publish the built database to GitHub Releases as a versioned artifact and
  download it at runtime, with a local-build fallback.
- Be fully fleet-compatible (Tool-Naming-Standard-v1, Response-Envelope-Standard-v1)
  and router-ready (drop-in `servers.yaml` entry for `genefoundry-router`).
- Reuse `mondo-link`'s domain-agnostic MCP scaffolding near-verbatim to minimize
  novel surface area and stay consistent with the fleet.

## 3. Non-goals

- **Not clinical decision support.** Research use only; every payload carries an
  `unsafe_for_clinical_use` signal and the research-use statement.
- **No write/curation surface.** Read-only.
- **No live Orphanet API proxying.** All queries hit the local database. (The
  Orphadata REST API and JSON conversions exist but are derivatives; the XML
  files are canonical and are our source of truth.)
- **No ORDO/HOOM OWL ingestion in v1.** The XML products cover the required
  content as flat tables. OWL-graph ingestion is a possible future extension
  (see §13).
- **Not a Nomenclature-Pack / obsolete-code authority in v1.** We record
  obsolescence flags present in the XML but do not ingest the separate
  Orphanet Nomenclature Pack Excel differential files (future extension).

## 4. Background: the data source (verified 2026-06-18)

### 4.1 Access & format
- Orphadata XML files are **static, directly downloadable** (no auth, no
  registration, no API key). Verified: `en_product1.xml` returns HTTP 200,
  `Content-Type: text/xml`, ~53 MB, with `Last-Modified`/`ETag`.
- Served identically from `https://www.orphadata.com/data/xml/<file>`,
  `https://sciences.orphadata.com/data/xml/<file>`, and the legacy
  `http://www.orphadata.org/data/xml/<file>`. We use
  `https://www.orphadata.com/data/xml/` as the configurable default base.
- Files do **not** require Playwright. Playwright is used **once** to scrape the
  classifications listing page to enumerate the product-3 specialty IDs (which
  are non-sequential and not derivable from a fixed pattern); that ID list is
  then cached/committed so routine builds need no browser.
- Each file's root element is
  `<JDBOR date="YYYY-MM-DD ..." version="1.3.42 / 4.1.8 [...]" copyright="Orphanet (c) YYYY">`
  followed by an `<Availability><Licence>` block then a top-level list. We capture
  the `date` and `version` attributes as the canonical release stamp.

### 4.2 Products to ingest (all English XML)

All keyed on `OrphaCode` (1–6 digit integer). Each disorder also carries
`DisorderType` (granular kind) and `DisorderGroup` (classification level:
"Group of disorders" / "Disorder" / "Subtype of a disorder").

| Product | File | Contents |
|---|---|---|
| 1 | `en_product1.xml` | Nomenclature: name, synonyms, type, group, flags + cross-references (UMLS, OMIM, MONDO, ICD-10, ICD-11, GARD, MeSH, MedDRA) with mapping relation + validation status |
| 3 | `en_product3_<specialtyId>.xml` (×~33) | Poly-hierarchical classification trees, one file per medical specialty |
| 4 | `en_product4.xml` | Disease→HPO associations with HPOFrequency + optional DiagnosticCriteria |
| 6 | `en_product6.xml` | Disorder→Gene associations: symbol/name/synonyms, type, locus, association type + status, source PMIDs; gene xrefs (HGNC, OMIM, Ensembl, SwissProt/UniProt, Genatlas, Reactome, ClinVar) |
| 7 | `en_product7.xml` | Linearisation: single non-redundant parent per disease |
| 8 (funct) | `en_funct_consequences.xml` | Disability annotations (Orphanet Functioning Thesaurus, ICF-CY-derived) |
| 9 prev | `en_product9_prev.xml` | Epidemiology: prevalence records (type, class band, ValMoy, geography, qualification, validation status, source) |
| 9 ages | `en_product9_ages.xml` | Natural history: AverageAgeOfOnset list + TypeOfInheritance list |

Note: functional consequences breaks the `productN` filename convention
(`en_funct_consequences.xml`, not `product8`). Product 3 has **no** single
`en_product3.xml` (404) — it is per-specialty.

### 4.3 Scale (DB sizing)
~11,456 nomenclature disorders; ~9,957 linearised diseases; ~50k+ cross-references;
~4,000–4,500 genes with ~25k–30k gene-xref rows; ~110k–150k disorder-HPO rows;
tens of thousands of prevalence rows; ~7,374 disorders with onset/inheritance.
Raw XML totals ~150 MB; normalized SQLite expected in the low hundreds of MB —
comfortably a GitHub Release asset (gzipped smaller).

### 4.4 Versioning & cadence
Bi-annual releases (June/July and December). The filename is stable (overwritten
each release); the version lives **inside** the file (`<JDBOR date= version=>`).
New-release detection: cheap HTTP `Last-Modified`/`ETag` poll, confirmed by the
`<JDBOR>` stamp recorded in `meta`.

### 4.5 License & attribution
**Creative Commons Attribution 4.0 International (CC BY 4.0)** — confirmed inside
every file's `<Licence>` block (`CC-BY-4.0`) and on the legal notice. No
ShareAlike, no NoDerivatives, no NonCommercial. **Redistributing a derived SQLite
database as a GitHub Release artifact is explicitly permitted**, provided we (a)
attribute, (b) indicate changes made, (c) impose no further restrictions.

Required citation embedded in the artifact and `orphanet://citation`:
> "Orphadata Science: Free access data from Orphanet. © INSERM 1999. Available on
> http://sciences.orphadata.com/. Data version [date/version]." Changes:
> "Converted Orphadata XML to a normalized SQLite database."

### 4.6 Gotchas (must handle)
1. Product 3 is multi-file per specialty; enumerate/cache the specialty IDs.
2. Distinguish disorder vs group vs subtype (`DisorderGroup` level) — do not
   conflate the ~11.5k nomenclature entries with the ~10k diseases.
3. Cross-references carry `DisorderMappingRelation` (E/NTBT/BTNT/ND/W),
   ICD-specific `DisorderMappingICDRelation`, and `DisorderMappingValidationStatus`.
   Store all three; never flatten to a bare id.
4. Gene associations carry association type + `DisorderGeneAssociationStatus`
   (Assessed / Not yet assessed) + `SourceOfValidation` (PMIDs).
5. Prevalence is multi-valued and mixed-unit per disorder (multiple types,
   geographies, validation statuses; numeric `ValMoy` or only a class band).
6. No SNOMED / no ICD-9 in product 1. ICD-11 mappings carry a WHO Foundation URI.

## 5. Architecture — two planes (mirrors `mondo-link`)

The fleet's non-negotiable boundary:

- **Data plane** — returns plain dicts, raises typed exceptions:
  - `config.py` (pydantic-settings, env prefix `ORPHANET_LINK_`, nested `__`)
  - `constants.py` (SCHEMA_VERSION, XREF source prefixes, mapping-relation rank,
    citation/license strings)
  - `identifiers.py` (ORPHA / OMIM / ICD / HPO / HGNC CURIE normalization)
  - `exceptions.py` (typed hierarchy)
  - `logging_config.py` (structlog → stderr only)
  - `buildinfo.py` (git sha / built_at provenance)
  - `ingest/` — `downloader.py`, `parsers/` (one module per product),
    `builder.py`, `schema.sql`, `schema.py`, `lock.py`, `specialties.py`
    (cached product-3 ID list + Playwright refresh helper), `cli.py` (Typer:
    build / refresh / status / fetch-prebuilt)
  - `data/repository.py` (read-only raw parameterized SQL; FTS sanitization;
    schema-version tolerance)
  - `services/` — `orphanet_service.py` (singleton), `resolution.py`,
    `shaping.py`, `pagination.py`, `refresh.py`, `data_resolver.py`
    (prebuilt-download-or-local-build)
- **MCP plane** — domain-agnostic scaffolding copied from `mondo-link` and
  renamed: `mcp/facade.py`, `envelope.py`, `capabilities.py`, `schemas.py`,
  `annotations.py`, `next_commands.py`, `metrics.py`, `middleware.py`,
  `arg_help.py`, `resources.py`, `service_adapters.py`, `tools/` (one module per
  domain group) + `tools/_common.py` Annotated aliases. `run_mcp_tool` owns the
  `success`/`_meta`/error envelope; errors are **returned, never raised**.
- **Entrypoints:** `server.py` (`--transport unified|http|stdio`),
  `mcp_server.py` (stdio; sets `FASTMCP_*`/`NO_COLOR` before import, bootstraps
  data itself), and the `orphanet-link-data` Typer CLI.

Package `orphanet_link`; resource scheme `orphanet://`; router namespace
`orphanet`; console scripts `orphanet-link`, `orphanet-link-mcp`,
`orphanet-link-data`.

## 6. Ingestion pipeline

1. **Resolve data** (`services/data_resolver.py`): if `DATA__PREFER_PREBUILT`
   (default true), try to download the latest `data-*` GitHub Release asset
   (`orphanet.sqlite.gz`), verify sha256, decompress into `data_dir`, validate
   `meta.schema_version`. On any failure, fall back to local build.
2. **Download** (`ingest/downloader.py`): conditional GET (ETag/Last-Modified)
   reusing mondo-link's downloader engine; per-file cache in
   `download_cache.json`; 64 KiB streaming; required files re-raise on failure,
   optional files degrade gracefully. Product-3 specialty IDs come from
   `ingest/specialties.py` (committed list; `--refresh-specialties` re-scrapes
   the listing page via Playwright).
3. **Parse** (`ingest/parsers/`): `lxml.iterparse` streaming per product, each
   `clear()`-ing processed elements to stay memory-bounded. Each parser yields
   normalized row dicts. The `<JDBOR>` header is parsed once for the release
   stamp.
4. **Build** (`ingest/builder.py`): acquire `fcntl` lock → `mkstemp` temp DB →
   `executescript(schema.sql)` → batch-load (`BATCH=5000`) all tables → compute
   classification closure (memoized DFS with cycle guard, including self-pairs)
   → `INSERT INTO disorder_fts(disorder_fts) VALUES('optimize')` → write single
   `meta` row → commit/close → `os.replace(tmp, db_path)` (atomic swap).
5. **Refresh** decision: rebuild only if any upstream file changed (not all 304)
   or no readable DB exists.

## 7. Database schema (SQLite + FTS5)

Read-only at query time (`file:...?mode=ro`), WAL at build time. Raw parameterized
SQL (no ORM). Tables keyed on `orpha_code TEXT` unless noted.

```sql
-- Core nomenclature
CREATE TABLE disorder (
    orpha_code      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_upper      TEXT NOT NULL,
    disorder_type   TEXT,          -- e.g. Disease, Malformation syndrome, Clinical subtype
    disorder_group  TEXT,          -- Group of disorders | Disorder | Subtype of a disorder
    disorder_flag   TEXT,
    expert_link     TEXT,
    is_obsolete     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_disorder_name_upper ON disorder(name_upper);

CREATE TABLE disorder_synonym (orpha_code TEXT NOT NULL, synonym TEXT NOT NULL);
CREATE INDEX idx_disorder_synonym ON disorder_synonym(orpha_code);

CREATE TABLE disorder_lookup (    -- label/synonym -> code resolution
    lookup_label TEXT NOT NULL, orpha_code TEXT NOT NULL, label_type TEXT NOT NULL);
CREATE INDEX idx_disorder_lookup ON disorder_lookup(lookup_label);

CREATE VIRTUAL TABLE disorder_fts USING fts5 (
    orpha_code UNINDEXED, name, synonyms, tokenize='porter unicode61');

-- Cross-references (product 1)
CREATE TABLE xref (
    orpha_code        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- OMIM | MONDO | ICD-10 | ICD-11 | UMLS | GARD | MeSH | MedDRA
    object_id         TEXT NOT NULL,
    object_id_upper   TEXT NOT NULL,
    mapping_relation  TEXT,            -- E | NTBT | BTNT | ND | W
    icd_relation      TEXT,            -- ICD-specific relation when source is ICD-*
    validation_status TEXT,            -- Validated | not
    ref_uri           TEXT             -- WHO Foundation URI for ICD-11
);
CREATE INDEX idx_xref_orpha ON xref(orpha_code);
CREATE INDEX idx_xref_obj   ON xref(source, object_id_upper);

-- Classification (product 3, poly-hierarchy) + precomputed closure
CREATE TABLE classification_edge (
    orpha_code TEXT NOT NULL, parent_code TEXT NOT NULL, specialty_id TEXT NOT NULL);
CREATE INDEX idx_class_edge_child  ON classification_edge(orpha_code);
CREATE INDEX idx_class_edge_parent ON classification_edge(parent_code);

CREATE TABLE classification_closure (orpha_code TEXT NOT NULL, ancestor_code TEXT NOT NULL);
CREATE INDEX idx_class_closure       ON classification_closure(orpha_code);
CREATE INDEX idx_class_closure_anc   ON classification_closure(ancestor_code);

CREATE TABLE specialty (specialty_id TEXT PRIMARY KEY, name TEXT NOT NULL);

-- Linearisation (product 7, single parent)
CREATE TABLE linearisation (orpha_code TEXT NOT NULL, parent_code TEXT);
CREATE INDEX idx_linearisation ON linearisation(orpha_code);

-- Genes (product 6)
CREATE TABLE gene (
    gene_symbol TEXT PRIMARY KEY, gene_name TEXT, gene_type TEXT, locus TEXT,
    hgnc_id TEXT, omim_id TEXT, ensembl_id TEXT, swissprot_id TEXT,
    genatlas_id TEXT, reactome_id TEXT, clinvar_id TEXT);

CREATE TABLE disorder_gene (
    orpha_code        TEXT NOT NULL,
    gene_symbol       TEXT NOT NULL,
    association_type  TEXT,   -- e.g. Disease-causing germline mutation(s) in
    association_status TEXT,  -- Assessed | Not yet assessed
    source_pmids      TEXT);
CREATE INDEX idx_disorder_gene_orpha ON disorder_gene(orpha_code);
CREATE INDEX idx_disorder_gene_sym   ON disorder_gene(gene_symbol);

-- Phenotypes (product 4)
CREATE TABLE phenotype (
    orpha_code TEXT NOT NULL, hpo_id TEXT NOT NULL, hpo_term TEXT,
    frequency TEXT,             -- Obligate | Very frequent | Frequent | Occasional | Very rare | Excluded
    diagnostic_criteria TEXT);
CREATE INDEX idx_phenotype_orpha ON phenotype(orpha_code);
CREATE INDEX idx_phenotype_hpo   ON phenotype(hpo_id);

-- Epidemiology (product 9 prev)
CREATE TABLE prevalence (
    orpha_code TEXT NOT NULL, prevalence_type TEXT, prevalence_class TEXT,
    val_moy REAL, geographic TEXT, qualification TEXT,
    validation_status TEXT, source TEXT);
CREATE INDEX idx_prevalence_orpha ON prevalence(orpha_code);

-- Natural history (product 9 ages)
CREATE TABLE age_of_onset   (orpha_code TEXT NOT NULL, onset TEXT NOT NULL);
CREATE TABLE inheritance    (orpha_code TEXT NOT NULL, inheritance TEXT NOT NULL);
CREATE INDEX idx_onset_orpha       ON age_of_onset(orpha_code);
CREATE INDEX idx_inheritance_orpha ON inheritance(orpha_code);

-- Disability (functional consequences)
CREATE TABLE disability (
    orpha_code TEXT NOT NULL, annotation TEXT, category TEXT,
    frequency TEXT, temporality TEXT, severity TEXT);
CREATE INDEX idx_disability_orpha ON disability(orpha_code);

-- Provenance (single row)
CREATE TABLE meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version  INTEGER,
    orphanet_version TEXT,     -- <JDBOR version=>
    orphanet_date    TEXT,     -- <JDBOR date=>
    source_urls      TEXT,     -- JSON map of product -> URL
    disorder_count   INTEGER, xref_count INTEGER, gene_count INTEGER,
    phenotype_count  INTEGER, prevalence_count INTEGER,
    build_utc        TEXT, build_duration_s REAL);
```

Repository patterns reused from mondo-link: FTS5 input sanitization (quote each
token, prefix-match last token, LIKE fallback on FTS error); mapping-relation
ranking via a `CASE` expression; one-row-per-disorder grouping for consistent
pagination totals; `PRAGMA`-based schema-version tolerance.

## 8. MCP tool surface

Unprefixed `verb_noun`, ≤50 chars, canonical verbs, fleet-canon argument names.
All `READ_ONLY_OPEN_WORLD`, all with declared `output_schema`, all accept
`response_mode` (minimal/compact/standard/full, default compact).

| Tool | Signature (abbrev.) | Purpose |
|---|---|---|
| `get_server_capabilities` | `(detail="summary")` | Discovery: tools, workflows, error taxonomy, limits, release |
| `get_diagnostics` | `()` | Index status, Orphanet release/version, counts, runtime metrics |
| `resolve_disease` | `(query)` | Free-text / ORPHA:n / OMIM:n / ICD / name / synonym → canonical {orpha_code, name, match_type} |
| `search_diseases` | `(query, limit=25, offset=0, include_obsolete=False)` | FTS over name/synonyms |
| `get_disease` | `(term, fields=None)` | Full record: type/group, synonyms, grouped xrefs, counts of genes/phenotypes/prevalence |
| `get_disease_genes` | `(term)` | Associated genes + association type/status + PMIDs + gene xrefs |
| `get_disease_phenotypes` | `(term, frequency=None)` | HPO terms + frequency + diagnostic-criteria flag |
| `get_disease_prevalence` | `(term)` | Prevalence records (epidemiology) |
| `get_disease_natural_history` | `(term)` | Age of onset + inheritance modes |
| `get_disease_disability` | `(term)` | Functional-consequence annotations |
| `get_disease_classification` | `(term, specialty=None)` | Parents/children within classification trees |
| `get_disease_ancestors` | `(term, limit=200, offset=0)` | Transitive classification ancestors (closure) |
| `get_disease_descendants` | `(term, limit=200, offset=0)` | Transitive classification descendants |
| `map_cross_ontology` | `(term, prefixes=None)` | A disorder's xrefs grouped by source |
| `resolve_xref` | `(xref_id, limit=50, offset=0)` | External CURIE (OMIM/MONDO/ICD/UMLS/...) → orpha_code(s) |
| `find_diseases_by_gene` | `(gene_symbol, limit=50, offset=0)` | Reverse: gene → disorders |
| `find_diseases_by_phenotype` | `(hpo_id, limit=50, offset=0)` | Reverse: HPO term → disorders |
| `resolve_disease_batch` | `(queries: list[str])` | Batch resolve, partial success per item |
| `get_disease_batch` | `(terms: list[str], fields=None)` | Batch fetch, partial success per item |

Workflow steering via `next_commands` (`after_*` chainers):
resolve → record → genes/phenotypes/prevalence/classification → cross-ontology.

## 9. Resources

`orphanet://capabilities` (full contract JSON), `orphanet://tools` (live tool
overview), `orphanet://usage`, `orphanet://citation`, `orphanet://license`
(CC BY 4.0 + required INSERM attribution + "changes made" note),
`orphanet://research-use`, `orphanet://reference`.

## 10. Response envelope & fleet conventions

Mirror `mondo-link` (the reference implementation of Response-Envelope-Standard-v1):

- Success: `{success: true, <payload>, _meta}`. `_meta` tiered by response_mode:
  minimal → `{tool, request_id}`; compact → adds `next_commands` +
  `capabilities_version`; standard/full → adds `elapsed_ms`. `source="orphanet"`.
  `orphanet_version` stamped on every record. `recommended_citation` +
  research-use line declared once in capabilities/resources (not per-call).
- Error (returned, never raised): `{success: false, error_code, message,
  retryable, recovery_action, _meta}`. Taxonomy: `invalid_input`, `not_found`,
  `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`,
  `internal_error`. Enriched: `ambiguous_query` → candidates (+next_commands);
  `not_found` → suggestions; obsolete → replaced_by/successor.
- `capabilities_version` = first 16 hex of SHA-256 of the discovery contract with
  volatile keys excluded, cached per Orphanet release.
- Every tool declares a permissive `output_schema` (validates success + error
  across all response modes); enforced by a test.

## 11. Artifact publishing (novel — no fleet precedent)

**`.github/workflows/build-data.yml`**
- Triggers: `schedule` (weekly cron — catches the bi-annual release within a
  week), `workflow_dispatch`, and `push` touching `orphanet_link/ingest/**`.
- Steps: checkout → `setup-uv-python` composite action → `uv sync` →
  `uv run orphanet-link-data build` (downloads upstream XML, builds
  `data/orphanet.sqlite`) → read `meta.orphanet_version` → compute tag
  `data-<version>` → if a Release for that tag already exists, exit (idempotent)
  → gzip the DB, write `.sha256` and `manifest.json` (version, date, counts,
  schema_version, build_utc) → create the Release and upload assets via
  `softprops/action-gh-release`.

**Runtime resolver** (`services/data_resolver.py`)
- `DATA__PREFER_PREBUILT` (default true), `DATA__RELEASE_REPO`
  (default `<owner>/orphanet-link`), `DATA__RELEASE_TAG` (default `latest`):
  resolve the latest `data-*` release → download `orphanet.sqlite.gz` → verify
  sha256 → decompress to `data_dir` → validate `schema_version` compatibility.
- On any failure (offline, missing asset, schema mismatch), **fall back to local
  build** (downloader + parsers + builder).
- Docker entrypoint: try fetch-prebuilt; if it fails, build; then serve.

**`.github/workflows/ci.yml`**
- lint (ruff) + format-check + `lint-loc` (≤500 lines/file) + mypy strict +
  pytest against a tiny fixture DB built from checked-in mini-XML fixtures.

Versioning: artifact tag = Orphanet data version (`data-<JDBOR version>`),
`schema_version` stamped in `meta`; server checks schema compatibility on load
and rejects an incompatible prebuilt DB (then rebuilds).

## 12. Testing strategy

- `pytest` + `pytest-asyncio` (auto) + `pytest-cov` + `pytest-xdist` + `respx`.
- `tests/fixtures/` holds small but real XML samples for each product (a handful
  of disorders exercising xref relations, gene status, HPO frequencies, multi
  prevalence, onset/inheritance, a 2-level classification).
- Session fixture builds a real tiny SQLite from the fixtures; layered fixtures
  `built_db → repo → service → facade` (FastMCP with the fixture service
  injected).
- `respx` tests for the downloader (200 → 304 revalidation, 500 → error,
  optional-file degradation) and the prebuilt data-resolver (asset present /
  absent / sha mismatch → fallback).
- Invariant guards: `test_tool_names` (verb_noun ≤50, canonical verbs, no
  self-prefix), `test_output_schemas` (every real output validates),
  `test_envelope_contract`. Coverage `fail_under = 80`.

## 13. Packaging & ops

- hatchling + uv (`uv.lock`), Python ≥3.12, ruff (line 100, google docstrings),
  mypy `strict`, ≤500-line file budget via `scripts/check_file_size.py`.
- Runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2.11`,
  `pydantic-settings`, `httpx`, `lxml`, `structlog`, `orjson`, `rich`, `typer`,
  `mcp[cli]`, `fastmcp>=3.2,<4`. Build/CI extra: `playwright` (specialty-ID
  refresh only, not a runtime dep of the server).
- Makefile: `install`, `lock`, `format[-check]`, `lint[-fix]`, `lint-loc`,
  `typecheck`, `test[-fast/-cov]`, `check`, `ci-local`, `data`, `data-refresh`,
  `data-status`, `data-fetch`, `dev`, `mcp-serve`, `docker-*`, `verify-deploy`.
- Multi-stage Docker (`python:3.12-slim`, non-root `app`, `VOLUME /app/data`,
  `EXPOSE 8000`, healthcheck on `/health` with a long start-period; entrypoint
  fetch-prebuilt-or-build then serve). dev/prod/npm compose overlays.
- `AGENTS.md` (authoritative contributor guide: two-plane boundary, invariants,
  definition-of-done) + lean `CLAUDE.md` pointer + `README.md`.

## 14. Router integration

Prepared (not pushed) `servers.yaml` entry for `genefoundry-router`:
```yaml
- { name: orphanet, repo: berntpopp/orphanet-link, url_env: GF_ORPHANET_URL,
    namespace: orphanet, tags: [disease, ontology, rare-disease, epidemiology, gene, phenotype],
    entrypoints: [resolve_disease] }
```
plus `GF_ORPHANET_URL=https://orphanet-link.genefoundry.org/mcp` documented in
`.env.example`. Compliance verified locally against the router's
`doctor --strict-naming` rules (regex `^[a-z0-9_]{1,50}$`, canonical verbs).
Self-healing hints (`fallback_tool`, `next_commands[].tool`) use **bare** leaf
names (the router namespaces them).

## 15. Risks & mitigations

- **Product-3 specialty-ID drift** — IDs may change between releases. Mitigation:
  `--refresh-specialties` Playwright helper + committed cache; build logs a
  warning if a cached ID 404s.
- **XML schema evolution** — Orphadata occasionally revises XSDs. Mitigation:
  parsers code defensively (missing optional elements tolerated), and a fixture
  per product catches regressions; XSDs are referenced in `docs/`.
- **DB size in CI / release limits** — gzip the SQLite; GitHub Release assets
  allow up to 2 GB, far above our low-hundreds-of-MB DB.
- **First-in-fleet artifact pipeline** — no sibling to copy. Mitigation: keep the
  build/local-fallback half identical to mondo-link's proven downloader+builder;
  only the release-publish and prebuilt-fetch halves are new and are unit-tested
  with `respx`.

## 16. Build plan (parallelization)

After the implementation plan (writing-plans), dispatch parallel agents per
independent module group, using git-worktree isolation where they write
concurrently:
1. Scaffolding + packaging + config/constants/identifiers/exceptions/logging.
2. MCP plane (copy + rename from mondo-link) + tool stubs + schemas.
3. Ingest: downloader + per-product parsers + schema.sql + builder + specialties.
4. data/repository + services (resolution/shaping/pagination/data_resolver).
5. CI/artifact workflows + Docker + Makefile.
6. Tests + fixtures.
7. Docs (README/AGENTS.md/CLAUDE.md) + router `servers.yaml` entry.

## 17. Future extensions (out of scope for v1)

- ORDO/HOOM OWL ingestion for true ontology-graph queries.
- Nomenclature Pack differential ingestion for authoritative obsolete-code
  redirects.
- ChatGPT-compatible `search`/`fetch` tool pair.
- Tool profiles (lite/full) via an env switch.
