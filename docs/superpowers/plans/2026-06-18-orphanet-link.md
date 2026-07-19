# orphanet-link Implementation Plan

> Historical record — this plan records the design and implementation sequence as of its date.
> Current behavior is defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only MCP server that grounds rare-disease queries in Orphanet scientific knowledge files, backed by a locally-built SQLite/FTS5 database published to GitHub Releases as a versioned artifact.

**Architecture:** Two-plane design mirroring `mondo-link` — a data plane (config, ingest, repository, services returning plain dicts + typed exceptions) and a domain-agnostic MCP plane (`mcp/`) copied from `mondo-link` and renamed. Orphadata English XML is streamed with `lxml.iterparse`, normalized into a SQLite/FTS5 DB with precomputed classification closure, queried read-only. The DB is built in CI, published as a GitHub Release asset, and fetched at runtime with a local-build fallback.

**Tech Stack:** Python ≥3.12, uv + hatchling, FastMCP 3.x, FastAPI/uvicorn, pydantic v2 + pydantic-settings, httpx, lxml, structlog, typer, sqlite3 + FTS5, pytest + respx, ruff, mypy. Playwright (build-time only, for product-3 specialty-ID discovery).

## Global Constraints

- Python `requires-python = ">=3.12"`. (verbatim from spec §13)
- Package `orphanet_link`; console scripts `orphanet-link`, `orphanet-link-mcp`, `orphanet-link-data`.
- Env prefix `ORPHANET_LINK_` (nested delimiter `__`). Resource scheme `orphanet://`. Router namespace `orphanet`. Server name `orphanet-link`.
- MCP tools: unprefixed `verb_noun`, regex `^[a-z0-9_]{1,50}$`, canonical verbs only (`get, search, list, resolve, find, compare, compute` + `predict, analyze, annotate, submit, export, generate, download`). NO self-prefix (`orphanet_*`).
- Response envelope mirrors `mondo-link`: success `{success, <payload>, _meta}`; error returned-never-raised `{success: false, error_code, message, retryable, recovery_action, _meta}`; `error_code` ∈ `{invalid_input, not_found, ambiguous_query, data_unavailable, rate_limited, upstream_unavailable, internal_error}`. Default `response_mode="compact"` (modes: minimal/compact/standard/full).
- `_meta.source = "orphanet"`; `orphanet_version` stamped on records; `recommended_citation` + research-use line declared once in capabilities/resources, not per call.
- License: data is CC BY 4.0; required citation string (spec §4.5) embedded in artifact manifest and `orphanet://citation`/`orphanet://license`.
- File-size budget: ≤500 lines per `.py` file, enforced by `scripts/check_file_size.py`.
- ruff line-length 100, google docstrings; mypy `strict = true`; pytest coverage `fail_under = 80`.
- SQLite `SCHEMA_VERSION` integer stamped in `meta`; server rejects an incompatible prebuilt DB and rebuilds.
- Data source base URL default `https://www.orphadata.com/data/xml/` (configurable via `ORPHANET_LINK_DATA__BASE_URL`).

## Reference template & rename map

The reference implementation is at `/home/bernt-popp/development/mondo-link`. Many tasks **copy a file from there and apply this rename map** (apply with `sed`, then hand-verify):

| mondo-link token | orphanet-link token |
|---|---|
| `mondo_link` | `orphanet_link` |
| `mondo-link` | `orphanet-link` |
| `MONDO_LINK_` | `ORPHANET_LINK_` |
| `mondo://` | `orphanet://` |
| `MondoService` / `get_mondo_service` / `set_mondo_service` / `reset_mondo_service` | `OrphanetService` / `get_orphanet_service` / `set_orphanet_service` / `reset_orphanet_service` |
| `mondo_id` (payload key) | `orpha_code` |
| `mondo_version` (meta/record key) | `orphanet_version` |
| `MONDO_SERVER_INSTRUCTIONS` | `ORPHANET_SERVER_INSTRUCTIONS` |
| `name="mondo-link"` (FastMCP) | `name="orphanet-link"` |

"Copy-and-rename" tasks are concrete operations, not placeholders: the source file exists, the transform is mechanical, and the deliverable is verified by the renamed-and-copied tests passing.

## File structure (target)

```
orphanet-link/
├── pyproject.toml, uv.lock, Makefile, README.md, AGENTS.md, CLAUDE.md, .env.example
├── server.py, mcp_server.py
├── orphanet_link/
│   ├── __init__.py, config.py, constants.py, identifiers.py, exceptions.py
│   ├── logging_config.py, buildinfo.py, app.py, server_manager.py
│   ├── ingest/
│   │   ├── __init__.py, downloader.py, lock.py, schema.sql, schema.py
│   │   ├── specialties.py, builder.py, cli.py
│   │   └── parsers/ (__init__.py, _common.py, product1.py, product3.py,
│   │       product4.py, product6.py, product7.py, product9_prev.py,
│   │       product9_ages.py, funct_consequences.py)
│   ├── data/ (__init__.py, repository.py)
│   ├── services/ (__init__.py, orphanet_service.py, resolution.py,
│   │   shaping.py, pagination.py, refresh.py, data_resolver.py)
│   └── mcp/ (facade.py, envelope.py, capabilities.py, schemas.py, annotations.py,
│       next_commands.py, metrics.py, middleware.py, arg_help.py, resources.py,
│       service_adapters.py, tools/{_common,discovery,diseases,associations,classification,xref,batch}.py)
├── scripts/ (check_file_size.py, check_deployed_freshness.py)
├── docker/ (Dockerfile, docker-compose.yml, docker-compose.npm.yml, entrypoint.sh)
├── .github/ (actions/setup-uv-python/action.yml, workflows/ci.yml, workflows/build-data.yml)
└── tests/ (conftest.py, fixtures/*.xml, unit/test_*.py)
```

---

## Phase 0 — Scaffolding & packaging

### Task 1: Project skeleton, packaging, config

**Files:**
- Create: `pyproject.toml`, `Makefile`, `scripts/check_file_size.py`, `scripts/check_deployed_freshness.py`
- Create: `orphanet_link/__init__.py`, `orphanet_link/config.py`, `orphanet_link/constants.py`, `orphanet_link/identifiers.py`, `orphanet_link/exceptions.py`, `orphanet_link/logging_config.py`, `orphanet_link/buildinfo.py`
- Test: `tests/unit/test_config.py`, `tests/unit/test_identifiers.py`

**Interfaces:**
- Produces: `orphanet_link.config.ServerSettings` (pydantic-settings, `env_prefix="ORPHANET_LINK_"`, nested `data` section with `base_url: str`, `data_dir: Path`, `db_path: Path`, `prefer_prebuilt: bool=True`, `release_repo: str`, `release_tag: str="latest"`). `orphanet_link.constants.SCHEMA_VERSION: int = 1`, `XREF_SOURCES`, `MAPPING_RELATION_RANK`, `CITATION`, `LICENSE_*`. `identifiers.normalize_orpha_code(s) -> str` (strips `ORPHA:`/`Orphanet:` prefix, returns bare digits), `identifiers.parse_curie(s) -> tuple[str|None, str]`.

- [ ] **Step 1:** Copy `pyproject.toml`, `Makefile`, `scripts/check_file_size.py`, `scripts/check_deployed_freshness.py` from mondo-link; apply the rename map. In `pyproject.toml` add `lxml>=5` to runtime deps and `playwright` to the dev group; set the three console scripts. In `Makefile` add targets `data-fetch` (`uv run orphanet-link-data fetch`) and keep `data`/`data-refresh`/`data-status`.
- [ ] **Step 2:** Copy `mondo_link/logging_config.py`, `buildinfo.py`, `exceptions.py` from mondo-link; apply rename map. Verify the exception hierarchy names are domain-neutral (`DataUnavailableError`, `NotFoundError`, `AmbiguousQueryError`, `DownloadError`, `BuildError`, `InvalidInputError`).
- [ ] **Step 3: Write the failing test** `tests/unit/test_config.py`:

```python
from orphanet_link.config import ServerSettings

def test_defaults_and_env_prefix(monkeypatch):
    monkeypatch.setenv("ORPHANET_LINK_DATA__BASE_URL", "https://example.test/xml/")
    s = ServerSettings()
    assert s.data.base_url == "https://example.test/xml/"
    assert s.data.prefer_prebuilt is True
    assert s.data.db_path.name == "orphanet.sqlite"
```

- [ ] **Step 4:** Run `uv run pytest tests/unit/test_config.py -v` → FAIL (no module).
- [ ] **Step 5:** Write `orphanet_link/config.py` adapting mondo-link's `config.py`: a `DataSettings` nested model with `base_url: str = "https://www.orphadata.com/data/xml/"`, `data_dir: Path`, computed `db_path = data_dir / "orphanet.sqlite"`, `prefer_prebuilt: bool = True`, `release_repo: str = "berntpopp/orphanet-link"`, `release_tag: str = "latest"`; `ServerSettings(BaseSettings, env_prefix="ORPHANET_LINK_", env_nested_delimiter="__")`.
- [ ] **Step 6:** Run the test → PASS.
- [ ] **Step 7: Write the failing test** `tests/unit/test_identifiers.py`:

```python
from orphanet_link.identifiers import normalize_orpha_code, parse_curie

def test_normalize_orpha_code():
    assert normalize_orpha_code("ORPHA:166024") == "166024"
    assert normalize_orpha_code("Orphanet:166024") == "166024"
    assert normalize_orpha_code("166024") == "166024"

def test_parse_curie():
    assert parse_curie("OMIM:607131") == ("OMIM", "607131")
    assert parse_curie("plain text") == (None, "plain text")
```

- [ ] **Step 8:** Run → FAIL. **Step 9:** Write `orphanet_link/identifiers.py`. **Step 10:** Run → PASS.
- [ ] **Step 11:** Write `orphanet_link/constants.py`: `SCHEMA_VERSION = 1`; `XREF_SOURCES = ["OMIM","MONDO","ICD-10","ICD-11","UMLS","GARD","MeSH","MedDRA"]`; `MAPPING_RELATION_RANK = {"E":0,"NTBT":1,"BTNT":2,"ND":3,"W":4}`; `CITATION` and `LICENSE_NAME="CC-BY-4.0"`, `LICENSE_URL`, `ATTRIBUTION` strings from spec §4.5.
- [ ] **Step 12: Commit**

```bash
git add -A && git commit -m "feat: project skeleton, packaging, config, identifiers"
```

---

## Phase 1 — Data model & build pipeline

### Task 2: SQLite schema

**Files:** Create `orphanet_link/ingest/__init__.py`, `orphanet_link/ingest/schema.sql`, `orphanet_link/ingest/schema.py`. Test: `tests/unit/test_schema.py`.

**Interfaces:** Produces `schema.load_schema_sql() -> str`. The DDL is exactly spec §7.

- [ ] **Step 1:** Create `schema.sql` with the full DDL from spec §7 (all tables: disorder, disorder_synonym, disorder_lookup, disorder_fts, xref, classification_edge, classification_closure, specialty, linearisation, gene, disorder_gene, phenotype, prevalence, age_of_onset, inheritance, disability, meta), preceded by `PRAGMA journal_mode = WAL; PRAGMA foreign_keys = OFF;`.
- [ ] **Step 2:** Copy mondo-link's `ingest/schema.py` (10-line loader reading the sibling `schema.sql`); rename.
- [ ] **Step 3: Write failing test** `tests/unit/test_schema.py`:

```python
import sqlite3
from orphanet_link.ingest.schema import load_schema_sql

def test_schema_executes_and_has_fts():
    conn = sqlite3.connect(":memory:")
    conn.executescript(load_schema_sql())
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"disorder","xref","gene","disorder_gene","phenotype","prevalence","meta"} <= tables
    conn.execute("INSERT INTO disorder_fts(orpha_code,name,synonyms) VALUES('1','x','y')")
```

- [ ] **Step 4:** Run → FAIL. **Step 5:** ensure `schema.sql` content correct. **Step 6:** Run → PASS. **Step 7: Commit** `feat: sqlite schema`.

### Task 3: Build lock + conditional downloader + specialty IDs

**Files:** Create `orphanet_link/ingest/lock.py`, `orphanet_link/ingest/downloader.py`, `orphanet_link/ingest/specialties.py`. Test: `tests/unit/test_downloader.py`, `tests/unit/test_lock.py`.

**Interfaces:**
- Produces: `lock.build_lock(data_dir)` (context manager, fcntl). `downloader.download_files(config, files: dict[str,str], optional: set[str]) -> BulkDownload` where `BulkDownload.not_modified: bool` and `.paths: dict[str, Path]`; conditional GET via `download_cache.json`. `specialties.SPECIALTY_IDS: list[str]` (committed list) and `specialties.product3_files() -> dict[str,str]` mapping `f"en_product3_{sid}"` → filename.

- [ ] **Step 1:** Copy mondo-link `ingest/lock.py` and `ingest/downloader.py`; apply rename map. The downloader engine is domain-neutral — change only the filename map plumbing so it accepts a `files` dict.
- [ ] **Step 2:** Copy mondo-link `tests/unit/test_downloader.py` and `test_lock.py`; rename; adjust the file map to Orphanet filenames. These use `@respx.mock` to assert 200→304 revalidation, 500→`DownloadError`, optional-file 404 degradation.
- [ ] **Step 3:** Run `uv run pytest tests/unit/test_downloader.py tests/unit/test_lock.py -v` → adjust until PASS.
- [ ] **Step 4:** Write `specialties.py` with `SPECIALTY_IDS` seeded from the known set (`["146","156","181","187", ...]` — confirm/extend at first run via the `--refresh-specialties` helper which scrapes `https://www.orphadata.com/classifications/` with Playwright). Include a `refresh_specialty_ids() -> list[str]` Playwright function guarded by an import-time try/except so the runtime server never needs Playwright.
- [ ] **Step 5: Commit** `feat: build lock, conditional downloader, specialty ids`.

### Task 4: Parser scaffolding + product1 parser (xrefs + nomenclature)

**Files:** Create `orphanet_link/ingest/parsers/__init__.py`, `orphanet_link/ingest/parsers/_common.py`, `orphanet_link/ingest/parsers/product1.py`. Test: `tests/fixtures/en_product1.xml`, `tests/unit/test_parser_product1.py`.

**Interfaces:**
- Produces: `_common.iter_disorders(path, wrapper, item)` — generic `lxml.iterparse` generator yielding `Disorder` elements under a wrapper, calling `.clear()` for memory safety; `_common.text(el, tag)`, `_common.named(el, tag)` (returns inner `<Name>` text), `_common.relation_code(name)` (extracts leading token e.g. `"E"` from `"E (Exact mapping...)"`), `_common.jdbor_stamp(path) -> tuple[str,str]` (date, version). `product1.parse(path) -> Product1Result` with `.disorders: list[dict]` (orpha_code, name, disorder_type, disorder_group, disorder_flag, expert_link, synonyms, definition) and `.xrefs: list[dict]` (orpha_code, source, object_id, mapping_relation, icd_relation, validation_status, ref_uri).

- [ ] **Step 1:** Create `tests/fixtures/en_product1.xml` — a minimal but real-structured file: `<JDBOR date="2025-12-09 07:06:32" version="1.3.42 / 4.1.8">` with `<Availability>...CC-BY-4.0...</Availability>` and a `<DisorderList count="2">` containing 2 `<Disorder>` copied/trimmed from the real file (the verified 166024 example with its 5 ExternalReferences incl. ICD-11 with RefUrl, MONDO, ICD-10, OMIM, UMLS, plus a SummaryInformation/Definition; and one more with a SynonymList of 2).
- [ ] **Step 2: Write failing test** `tests/unit/test_parser_product1.py`:

```python
from pathlib import Path
from orphanet_link.ingest.parsers import product1

FX = Path(__file__).parent.parent / "fixtures" / "en_product1.xml"

def test_product1_parses_disorder_and_xrefs():
    res = product1.parse(FX)
    d = {x["orpha_code"]: x for x in res.disorders}["166024"]
    assert d["name"].startswith("Multiple epiphyseal dysplasia")
    assert d["disorder_type"] == "Disease"
    assert d["disorder_group"] == "Disorder"
    assert d["definition"].startswith("A rare primary bone dysplasia")
    xr = [x for x in res.xrefs if x["orpha_code"] == "166024"]
    omim = next(x for x in xr if x["source"] == "OMIM")
    assert omim["object_id"] == "607131" and omim["mapping_relation"] == "E"
    icd11 = next(x for x in xr if x["source"] == "ICD-11")
    assert icd11["mapping_relation"] == "NTBT" and icd11["validation_status"] == "Validated"

def test_product1_jdbor_stamp():
    from orphanet_link.ingest.parsers._common import jdbor_stamp
    date, version = jdbor_stamp(FX)
    assert date.startswith("2025-12-09") and version.startswith("1.3.42")
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement `_common.py` and `product1.py`:

```python
# _common.py
from lxml import etree

def iter_disorders(path, wrapper, item="Disorder"):
    context = etree.iterparse(str(path), events=("end",), tag=item)
    for _event, el in context:
        yield el
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]

def text(el, tag):
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None

def named(el, tag):
    child = el.find(f"{tag}/Name")
    return child.text.strip() if child is not None and child.text else None

def relation_code(name):
    return name.split()[0] if name else None

def jdbor_stamp(path):
    for _e, el in etree.iterparse(str(path), events=("start",), tag="JDBOR"):
        return el.get("date"), el.get("version")
    return None, None
```

```python
# product1.py
from dataclasses import dataclass, field
from . import _common as c

@dataclass
class Product1Result:
    disorders: list = field(default_factory=list)
    xrefs: list = field(default_factory=list)

def parse(path):
    res = Product1Result()
    for d in c.iter_disorders(path, "DisorderList"):
        code = c.text(d, "OrphaCode")
        if not code:
            continue
        definition = None
        ts = d.find("SummaryInformationList/SummaryInformation/TextSectionList/TextSection")
        if ts is not None:
            contents = ts.find("Contents")
            definition = contents.text.strip() if contents is not None and contents.text else None
        res.disorders.append({
            "orpha_code": code,
            "name": c.text(d, "Name"),
            "disorder_type": c.named(d, "DisorderType"),
            "disorder_group": c.named(d, "DisorderGroup"),
            "disorder_flag": c.text(d.find("DisorderFlagList/DisorderFlag") or d, "Value")
                              if d.find("DisorderFlagList/DisorderFlag") is not None else None,
            "expert_link": c.text(d, "ExpertLink"),
            "synonyms": [s.text.strip() for s in d.findall("SynonymList/Synonym") if s.text],
            "definition": definition,
        })
        for ext in d.findall("ExternalReferenceList/ExternalReference"):
            res.xrefs.append({
                "orpha_code": code,
                "source": c.text(ext, "Source"),
                "object_id": c.text(ext, "Reference"),
                "mapping_relation": c.relation_code(c.named(ext, "DisorderMappingRelation")),
                "icd_relation": c.relation_code(c.named(ext, "DisorderMappingICDRelation")),
                "validation_status": c.named(ext, "DisorderMappingValidationStatus"),
                "ref_uri": c.text(ext, "DisorderMappingICDRefUrl"),
            })
    return res
```

- [ ] **Step 5:** Run → PASS. **Step 6: Commit** `feat: product1 parser (nomenclature + xrefs)`.

### Task 5: product4 parser (HPO phenotypes)

**Files:** Create `orphanet_link/ingest/parsers/product4.py`. Test: `tests/fixtures/en_product4.xml`, `tests/unit/test_parser_product4.py`.

**Interfaces:** Produces `product4.parse(path) -> list[dict]` rows `{orpha_code, hpo_id, hpo_term, frequency, diagnostic_criteria}`. Wrapper is `HPODisorderSetStatusList` and each `<HPODisorderSetStatus>` contains a `<Disorder>` — iterate on `Disorder` items directly.

- [ ] **Step 1:** Create fixture from the verified Alexander-disease structure (Disorder OrphaCode 58 with ≥2 `HPODisorderAssociation`, each `HPO/HPOId`, `HPO/HPOTerm`, `HPOFrequency/Name`).
- [ ] **Step 2: Write failing test** asserting a row `{orpha_code:"58", hpo_id:"HP:0000256", hpo_term:"Macrocephaly", frequency:"Very frequent (99-80%)"}` is present.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement:

```python
from . import _common as c

def parse(path):
    rows = []
    for d in c.iter_disorders(path, "HPODisorderSetStatusList", item="Disorder"):
        code = c.text(d, "OrphaCode")
        for a in d.findall("HPODisorderAssociationList/HPODisorderAssociation"):
            rows.append({
                "orpha_code": code,
                "hpo_id": c.text(a, "HPO/HPOId"),
                "hpo_term": c.text(a, "HPO/HPOTerm"),
                "frequency": c.named(a, "HPOFrequency"),
                "diagnostic_criteria": c.named(a, "DiagnosticCriteria"),
            })
    return rows
```

- [ ] **Step 5:** Run → PASS. **Step 6: Commit** `feat: product4 parser (HPO phenotypes)`.

### Task 6: product6 parser (genes)

**Files:** Create `orphanet_link/ingest/parsers/product6.py`. Test: `tests/fixtures/en_product6.xml`, `tests/unit/test_parser_product6.py`.

**Interfaces:** Produces `product6.parse(path) -> Product6Result` with `.genes: list[dict]` (gene_symbol, gene_name, gene_type, locus, + xref columns hgnc_id/omim_id/ensembl_id/swissprot_id/genatlas_id/reactome_id/clinvar_id) and `.associations: list[dict]` (orpha_code, gene_symbol, association_type, association_status, source_pmids). Gene xref `Source` values map: `HGNC→hgnc_id, OMIM→omim_id, Ensembl→ensembl_id, SwissProt→swissprot_id, Genatlas→genatlas_id, Reactome→reactome_id, ClinVar→clinvar_id`.

- [ ] **Step 1:** Create fixture from verified structure (Disorder 166024 → `DisorderGeneAssociation` with `SourceOfValidation`=`22587682[PMID]`, `Gene` Symbol `KIF7`, GeneType, 7 ExternalReferences incl HGNC 30497 / OMIM 611254 / Ensembl ENSG00000166813, plus `DisorderGeneAssociationType/Name` and `DisorderGeneAssociationStatus/Name`).
- [ ] **Step 2: Write failing test** asserting gene `KIF7` has `hgnc_id=="30497"`, `ensembl_id=="ENSG00000166813"`, and an association row `{orpha_code:"166024", gene_symbol:"KIF7", source_pmids:"22587682[PMID]"}`.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement with a `_GENE_XREF = {"HGNC":"hgnc_id", "OMIM":"omim_id", "Ensembl":"ensembl_id", "SwissProt":"swissprot_id", "Genatlas":"genatlas_id", "Reactome":"reactome_id", "ClinVar":"clinvar_id"}` map; dedupe genes by symbol into a dict; collect associations per disorder. (Iterate `DisorderList`, then `DisorderGeneAssociationList/DisorderGeneAssociation`, read `Gene/Symbol`, `Gene/Name`, `Gene/GeneType/Name`, loop `Gene/ExternalReferenceList/ExternalReference` mapping Source→column, read `DisorderGeneAssociationType/Name`, `DisorderGeneAssociationStatus/Name`, `SourceOfValidation`.)
- [ ] **Step 5:** Run → PASS. **Step 6: Commit** `feat: product6 parser (genes)`.

### Task 7: product7 parser (linearisation) + product9_prev + product9_ages + funct_consequences

**Files:** Create `parsers/product7.py`, `parsers/product9_prev.py`, `parsers/product9_ages.py`, `parsers/funct_consequences.py`. Tests + fixtures for each.

**Interfaces:**
- `product7.parse(path) -> list[dict]` rows `{orpha_code, parent_code}` (parent = `DisorderDisorderAssociation/TargetDisorder/OrphaCode`).
- `product9_prev.parse(path) -> list[dict]` rows `{orpha_code, prevalence_type, prevalence_class, val_moy, geographic, qualification, validation_status, source}`.
- `product9_ages.parse(path) -> Ages` with `.onsets: list[(orpha_code, onset)]` and `.inheritance: list[(orpha_code, mode)]`.
- `funct_consequences.parse(path) -> list[dict]` rows `{orpha_code, annotation, frequency, temporality, severity}` (wrapper `DisorderDisabilityRelevanceList`, item `Disorder`).

- [ ] **Step 1:** For each product create a small fixture from the verified heads (product7: Disorder 166024 → TargetDisorder OrphaCode 93419; product9_prev: Disorder 166024 with 2 Prevalence incl one `PrevalenceClass`=`<1 / 1 000 000` and `ValMoy`; product9_ages: Disorder 166024 with onsets Infancy+Neonatal and inheritance Autosomal recessive; funct: Disorder 893 with ≥1 DisabilityDisorderAssociation).
- [ ] **Step 2:** Write one failing test per parser asserting the representative row. Run → FAIL.
- [ ] **Step 3:** Implement each parser following the product4 pattern. product7:

```python
from . import _common as c
def parse(path):
    rows = []
    for d in c.iter_disorders(path, "DisorderList"):
        code = c.text(d, "OrphaCode")
        for a in d.findall("DisorderDisorderAssociationList/DisorderDisorderAssociation"):
            rows.append({"orpha_code": code, "parent_code": c.text(a, "TargetDisorder/OrphaCode")})
    return rows
```
product9_prev: iterate `PrevalenceList/Prevalence`, read `PrevalenceType/Name`, `PrevalenceClass/Name`, `ValMoy` (float or None), `PrevalenceGeographic/Name`, `PrevalenceQualification/Name`, `PrevalenceValidationStatus/Name`, `Source`. product9_ages: iterate `AverageAgeOfOnsetList/AverageAgeOfOnset/Name` and `TypeOfInheritanceList/TypeOfInheritance/Name`. funct: wrapper `DisorderDisabilityRelevanceList`, item `Disorder`, iterate `DisabilityDisorderAssociationList/DisabilityDisorderAssociation` reading `Disability/Name`, `FrequenceDisability/Name`, `TemporalityDisability/Name`, `SeverityDisability/Name`.
- [ ] **Step 4:** Run all four → PASS. **Step 5: Commit** `feat: product7/9_prev/9_ages/funct parsers`.

### Task 8: product3 parser (classification trees) — confirm structure from sample

**Files:** Create `parsers/product3.py`. Test: `tests/fixtures/en_product3_156.xml` (trimmed real sample), `tests/unit/test_parser_product3.py`.

**Interfaces:** Produces `product3.parse(path, specialty_id) -> Product3Result` with `.edges: list[dict]` `{orpha_code, parent_code, specialty_id}` and `.specialty: dict|None` `{specialty_id, name}`.

- [ ] **Step 1:** Download a real sample: `curl -s https://www.orphadata.com/data/xml/en_product3_156.xml | head -c 4000` to confirm the exact element names (expected: a `ClassificationNodeRootList` → `ClassificationNode` → `Disorder` + nested `ClassificationNodeChildList/ClassificationNode` recursion). Trim a 2-level subtree into the fixture. **This is the one product whose tags must be confirmed at implementation time.**
- [ ] **Step 2: Write failing test** asserting a child→parent edge with the correct `specialty_id`.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement a recursive walk over the confirmed `ClassificationNode` tree: for each node read its `Disorder/OrphaCode`, then for each child node in `ClassificationNodeChildList` emit `{orpha_code: child_code, parent_code: node_code, specialty_id}` and recurse. Use `etree.parse` (these files are small per-specialty) rather than iterparse.
- [ ] **Step 5:** Run → PASS. **Step 6: Commit** `feat: product3 parser (classification trees)`.

### Task 9: Builder (assemble DB + closure + meta)

**Files:** Create `orphanet_link/ingest/builder.py`. Test: `tests/unit/test_builder.py`.

**Interfaces:** Produces `builder.build_database(config, paths: dict[str,Path]) -> Path`. `paths` maps product keys (`product1, product3_<sid>..., product4, product6, product7, product9_prev, product9_ages, funct`) to files. Computes `classification_closure` via memoized DFS over `classification_edge` (child→ancestor, incl self-pairs), with a cycle guard. Writes one `meta` row (schema_version, orphanet_version/date from `jdbor_stamp(product1)`, counts, build_utc, build_duration_s). Atomic: `mkstemp` + `os.replace`, under `build_lock`.

- [ ] **Step 1: Write failing test** `tests/unit/test_builder.py`: build from the fixtures, open the resulting DB read-only, assert `disorder` has the fixture codes, `xref` has the OMIM row, `disorder_gene` has KIF7, `phenotype` has the HP term, `classification_closure` contains a (child, ancestor) pair plus self-pairs, and `meta.orphanet_version` is set.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `builder.build_database` adapting mondo-link's `builder.py` (same atomic-swap + lock + batch-insert skeleton). Add a `_compute_closure(edges)` memoized-DFS helper. Insert FTS rows from disorder name+synonyms; populate `disorder_lookup` from names+synonyms (label_type `name`/`synonym`). Run `INSERT INTO disorder_fts(disorder_fts) VALUES('optimize')`.
- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `feat: database builder with closure + provenance`.

### Task 10: Ingest CLI (build / refresh / status / fetch)

**Files:** Create `orphanet_link/ingest/cli.py`. Test: `tests/unit/test_cli.py`.

**Interfaces:** Typer app with commands `build` (download all + build), `refresh` (conditional), `status` (print meta), `fetch` (delegate to `data_resolver.fetch_prebuilt`). Console entry `orphanet-link-data = "orphanet_link.ingest.cli:main"`. Consumes `downloader`, `builder`, `data_resolver`.

- [ ] **Step 1:** Copy mondo-link `ingest/cli.py`; rename; wire the Orphanet file map (product1, the product3 specialty set, product4/6/7/9_prev/9_ages/funct). `refresh` rebuilds only if `download_files(...).not_modified` is False or no readable DB exists.
- [ ] **Step 2:** Copy + adapt mondo-link `tests/unit/test_cli.py` (mock the downloader/builder). Run → adjust to PASS. **Step 3: Commit** `feat: ingest CLI (build/refresh/status/fetch)`.

---

## Phase 2 — Query layer

### Task 11: Read-only repository

**Files:** Create `orphanet_link/data/__init__.py`, `orphanet_link/data/repository.py`. Test: `tests/unit/test_repository.py`.

**Interfaces:** Produces `repository.OrphanetRepository(db_path)` (opens `file:...?mode=ro`, `row_factory=Row`). Methods (all return plain dicts/lists): `get_disorder(code)`, `resolve_label(label) -> list[dict]` (via disorder_lookup + FTS fallback), `search(query, limit, offset, include_obsolete) -> dict` (FTS5 with the sanitizer + LIKE fallback, paginated, `total`), `get_xrefs(code) -> list` (ranked by `MAPPING_RELATION_RANK` via CASE), `resolve_xref(source, object_id) -> list[code]`, `get_genes(code)`, `find_disorders_by_gene(symbol, limit, offset)`, `get_phenotypes(code, frequency)`, `find_disorders_by_phenotype(hpo_id, limit, offset)`, `get_prevalence(code)`, `get_natural_history(code)`, `get_disability(code)`, `get_classification(code) -> {parents, children}`, `get_ancestors(code, limit, offset)`, `get_descendants(code, limit, offset)`, `get_meta()`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_repository.py` exercising `get_disorder`, `search` (FTS hit + LIKE fallback for a punctuation query), `get_xrefs` ranking (E before NTBT), `resolve_xref("OMIM","607131")`, `get_genes`, `find_disorders_by_gene("KIF7")`, `get_phenotypes`, `get_ancestors` (closure), against the session `built_db` fixture (Task 19 provides it; for now build inline in the test using `builder.build_database`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `repository.py` adapting mondo-link's `data/repository.py` (reuse its `_fts_query` sanitizer verbatim, the CASE-rank pattern, GROUP BY collapse, and `PRAGMA`-based schema tolerance). Write Orphanet-specific SQL for each method.
- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `feat: read-only repository`.

### Task 12: Services — resolution, shaping, pagination, orphanet_service

**Files:** Create `orphanet_link/services/__init__.py`, `resolution.py`, `shaping.py`, `pagination.py`, `orphanet_service.py`. Test: `tests/unit/test_resolution.py`, `test_shaping.py`, `test_service.py`.

**Interfaces:** Produces `OrphanetService` singleton with one method per tool returning plain dicts (delegating to `OrphanetRepository`), `resolution.resolve(repo, query) -> dict` (cascade: ORPHA code → exact label → xref CURIE → FTS fuzzy; raises `AmbiguousQueryError`/`NotFoundError`), `shaping.shape(record, response_mode, fields)` (minimal/compact/standard/full + sparse `fields`), `pagination.truncation_block(total, limit, offset)`.

- [ ] **Step 1:** Copy mondo-link `services/shaping.py` and `pagination.py`; rename; adjust anchor keys to `{orpha_code, name, orphanet_version}`.
- [ ] **Step 2: Write failing tests** for `resolution.resolve` (ORPHA:166024 → exact; "Alexander disease" → exact label; "OMIM:607131" → via xref; ambiguous prefix → AmbiguousQueryError) and `shaping` (minimal keeps only anchors). Run → FAIL.
- [ ] **Step 3:** Implement `resolution.py`, `orphanet_service.py` (one method per tool: `resolve_disease`, `search_diseases`, `get_disease`, `get_disease_genes`, `get_disease_phenotypes`, `get_disease_prevalence`, `get_disease_natural_history`, `get_disease_disability`, `get_disease_classification`, `get_disease_ancestors`, `get_disease_descendants`, `map_cross_ontology`, `resolve_xref`, `find_diseases_by_gene`, `find_diseases_by_phenotype`). Each stamps `orphanet_version` from `repo.get_meta()`.
- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `feat: resolution, shaping, pagination, orphanet_service`.

### Task 13: Data resolver (prebuilt download + local-build fallback)

**Files:** Create `orphanet_link/services/data_resolver.py`, `orphanet_link/services/refresh.py`. Test: `tests/unit/test_data_resolver.py`.

**Interfaces:** Produces `data_resolver.ensure_database(config) -> Path` — if `config.data.prefer_prebuilt`: call `fetch_prebuilt(config)`; on failure fall back to `local_build(config)`. `fetch_prebuilt(config)`: GET `https://api.github.com/repos/{release_repo}/releases/{tag}` (or `/latest`), find asset `orphanet.sqlite.gz`, download, verify against the `.sha256` asset, gunzip into `data_dir`, validate `meta.schema_version == SCHEMA_VERSION` (raise `DataUnavailableError` on mismatch). `local_build(config)`: download upstream XML + `builder.build_database`.

- [ ] **Step 1: Write failing tests** with `@respx.mock`: (a) release JSON + gz asset + matching sha → DB placed; (b) sha mismatch → `DataUnavailableError`; (c) schema-version mismatch → `DataUnavailableError`; (d) `ensure_database` with prefer_prebuilt and a 404 release → falls back to `local_build` (mock `local_build`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `data_resolver.py` using `httpx` + `gzip` + `hashlib.sha256`. Copy mondo-link `services/refresh.py` (bootstrap/periodic) and rename; have its bootstrap call `ensure_database`.
- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `feat: data resolver (prebuilt fetch + local-build fallback)`.

---

## Phase 3 — MCP plane & server

### Task 14: Copy + rename the MCP scaffolding plane

**Files:** Create `orphanet_link/mcp/{__init__,facade,envelope,capabilities,schemas,annotations,next_commands,metrics,middleware,arg_help,resources,service_adapters}.py` and `orphanet_link/mcp/tools/{__init__,_common}.py`. Tests: copy mondo-link `tests/unit/{test_metrics,test_next_commands,test_capabilities,test_output_schemas,test_tool_names}.py`.

**Interfaces:** Produces `mcp.envelope.run_mcp_tool(name, call, context)`; `mcp.service_adapters.{get,set,reset}_orphanet_service`; `mcp.facade.create_orphanet_mcp() -> FastMCP`; `mcp.annotations.READ_ONLY_OPEN_WORLD`; `mcp.next_commands.after_*`; `mcp.capabilities` payload + `capabilities_version`.

- [ ] **Step 1:** Copy each mcp-plane file from `mondo_link/mcp/`; apply the rename map (`sed`). These are domain-agnostic per the mondo-link AGENTS.md.
- [ ] **Step 2:** In `resources.py` rewrite the `orphanet://` resource text (citation = spec §4.5, license = CC BY 4.0 + attribution, research-use disclaimer). In `capabilities.py` update the server description + tool list + workflow text for Orphanet. In `facade.py` set `name="orphanet-link"` and register the (initially empty) tool groups.
- [ ] **Step 3:** Copy + rename the listed tests. `test_tool_names.py` must encode the Global-Constraints regex/verbs. Run → fix renames until PASS.
- [ ] **Step 4: Commit** `feat: MCP scaffolding plane (envelope, capabilities, resources, facade)`.

### Task 15: Tool group — discovery (capabilities, diagnostics)

**Files:** Create `orphanet_link/mcp/tools/discovery.py`, `orphanet_link/mcp/schemas.py` (the discovery output schemas). Test: `tests/unit/test_tools_e2e.py` (start).

**Interfaces:** `register_discovery_tools(mcp)` registering `get_server_capabilities`, `get_diagnostics`. Consumes `OrphanetService.get_diagnostics()` and `capabilities` payload.

- [ ] **Step 1:** Copy mondo-link `mcp/tools/discovery.py`; rename; point `get_diagnostics` at `OrphanetService` (release version, counts from `meta`, runtime metrics).
- [ ] **Step 2: Write failing e2e test** invoking `get_server_capabilities.fn()` and `get_diagnostics.fn()` through the facade with a `FakeService`/fixture service, asserting `success` envelope + `_meta.source=="orphanet"`. Run → FAIL → wire → PASS. **Step 3: Commit** `feat: discovery tools`.

### Task 16: Tool group — diseases (resolve, search, get, batch)

**Files:** Create `orphanet_link/mcp/tools/diseases.py`, `orphanet_link/mcp/tools/batch.py`; extend `schemas.py`. Test: extend `test_tools_e2e.py`.

**Interfaces:** `register_disease_tools(mcp)` → `resolve_disease`, `search_diseases`, `get_disease`. `register_batch_tools(mcp)` → `resolve_disease_batch`, `get_disease_batch`. Each tool wraps a `call()` closure in `run_mcp_tool`, injects `after_*` next_commands, declares an `output_schema`.

- [ ] **Step 1:** Adapt mondo-link `tools/diseases.py` + `batch.py`. Map mondo's resolve/search/get onto `OrphanetService`. Add `fields` param to `get_disease`.
- [ ] **Step 2: Write failing e2e tests** per tool asserting envelope + payload keys (`orpha_code`, `name`) + `output_schema` validation. Run → FAIL → implement → PASS. **Step 3: Commit** `feat: disease tools + batch`.

### Task 17: Tool group — associations (genes, phenotypes, prevalence, natural history, disability)

**Files:** Create `orphanet_link/mcp/tools/associations.py`; extend `schemas.py`. Test: extend `test_tools_e2e.py`.

**Interfaces:** `register_association_tools(mcp)` → `get_disease_genes`, `get_disease_phenotypes`, `get_disease_prevalence`, `get_disease_natural_history`, `get_disease_disability`, `find_diseases_by_gene`, `find_diseases_by_phenotype`.

- [ ] **Step 1: Write failing e2e tests** for each (e.g. `get_disease_genes("ORPHA:166024")` returns a gene with `hgnc_id`; `find_diseases_by_gene("KIF7")` returns disorder 166024; `get_disease_phenotypes("ORPHA:58")` returns the HP term; `get_disease_prevalence` returns a class band; `get_disease_natural_history` returns onset+inheritance). Run → FAIL.
- [ ] **Step 2:** Implement `associations.py` (each tool: `run_mcp_tool` wrapper → `OrphanetService` method → shaped/paginated result + `next_commands`). Declare `output_schema`s.
- [ ] **Step 3:** Run → PASS. **Step 4: Commit** `feat: association tools (genes/phenotypes/prevalence/natural-history/disability)`.

### Task 18: Tool group — classification & cross-ontology

**Files:** Create `orphanet_link/mcp/tools/classification.py`, `orphanet_link/mcp/tools/xref.py`; extend `schemas.py`. Test: extend `test_tools_e2e.py`.

**Interfaces:** `register_classification_tools(mcp)` → `get_disease_classification`, `get_disease_ancestors`, `get_disease_descendants`. `register_xref_tools(mcp)` → `map_cross_ontology`, `resolve_xref`.

- [ ] **Step 1: Write failing e2e tests** (`get_disease_ancestors` uses closure; `map_cross_ontology("ORPHA:166024")` groups xrefs by source; `resolve_xref("OMIM:607131")` → 166024). Run → FAIL.
- [ ] **Step 2:** Implement both modules (adapt mondo-link `tools/hierarchy.py` + `xref.py`). Run → PASS. **Step 3: Commit** `feat: classification + cross-ontology tools`.

### Task 19: Server entrypoints, app, conftest fixtures, facade wiring

**Files:** Create `server.py`, `mcp_server.py`, `orphanet_link/server_manager.py`, `orphanet_link/app.py`. Test: `tests/conftest.py`, `tests/fixtures/` (all product fixtures), `tests/__init__.py`, `tests/unit/__init__.py`.

**Interfaces:** Produces the session fixture chain `built_db → repo → service → facade` (mirrors mondo-link conftest). `create_orphanet_mcp()` registers all five tool groups + capability resources + `ArgValidationMiddleware`. `server.py` `main()` with `--transport unified|http|stdio`; `mcp_server.py` stdio entry that bootstraps data via `data_resolver.ensure_database`.

- [ ] **Step 1:** Copy `server.py`, `mcp_server.py`, `mondo_link/server_manager.py`, `mondo_link/app.py`; apply rename map. Wire the unified lifespan to `data_resolver.ensure_database`.
- [ ] **Step 2:** Copy mondo-link `tests/conftest.py`; rename; point the `built_db` fixture at `builder.build_database` with the Orphanet fixtures; layer `repo`/`service`/`facade`.
- [ ] **Step 3:** In `facade.create_orphanet_mcp`, call all five `register_*` functions. Run the full suite `uv run pytest -q` → fix until green; run `make lint typecheck lint-loc`.
- [ ] **Step 4: Commit** `feat: server entrypoints, app, facade wiring, test fixtures`.

---

## Phase 4 — Delivery (Docker, CI, artifact pipeline, docs)

### Task 20: Docker

**Files:** Create `docker/{Dockerfile,docker-compose.yml,docker-compose.npm.yml,entrypoint.sh}`, `.env.docker.example`.

- [ ] **Step 1:** Copy mondo-link `docker/*`; apply rename map. In `entrypoint.sh` replace `mondo-link-data refresh` with: try `orphanet-link-data fetch` (prebuilt); on failure `orphanet-link-data build`; then `exec python server.py --transport unified`.
- [ ] **Step 2:** Validate: `docker compose -f docker/docker-compose.yml config >/dev/null`. **Step 3: Commit** `feat: docker (multi-stage, fetch-or-build entrypoint)`.

### Task 21: CI workflow + composite action

**Files:** Create `.github/actions/setup-uv-python/action.yml`, `.github/workflows/ci.yml`.

- [ ] **Step 1:** Copy hnf1b-db's `.github/actions/setup-uv-python/action.yml` (referenced in the fleet survey) or write a minimal composite that installs uv + Python 3.12 + `uv sync --group dev`.
- [ ] **Step 2:** Write `ci.yml`: on push/PR → checkout → setup-uv-python → `make format-check lint lint-loc typecheck` → `uv run pytest -q --cov` (against the committed fixtures; no network). Add a job step asserting tool-name compliance (`uv run pytest tests/unit/test_tool_names.py`).
- [ ] **Step 3:** Lint the YAML locally (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`). **Step 4: Commit** `ci: lint/type/test workflow`.

### Task 22: Artifact build-and-publish workflow (the novel piece)

**Files:** Create `.github/workflows/build-data.yml`.

**Interfaces:** Produces a GitHub Release tagged `data-<orphanet_version>` with assets `orphanet.sqlite.gz`, `orphanet.sqlite.gz.sha256`, `manifest.json`.

- [ ] **Step 1:** Write `build-data.yml`:
  - Triggers: `schedule` (`cron: "0 6 * * 1"` weekly), `workflow_dispatch`, `push` on `orphanet_link/ingest/**`.
  - Permissions: `contents: write`.
  - Steps: checkout → setup-uv-python → `uv run orphanet-link-data build` → a step that reads the DB `meta` and writes outputs:
    ```bash
    VERSION=$(uv run python -c "import sqlite3;print(sqlite3.connect('data/orphanet.sqlite').execute('select orphanet_version from meta').fetchone()[0])" | tr -d ' ' | tr '/' '-')
    TAG="data-${VERSION}"
    echo "tag=$TAG" >> "$GITHUB_OUTPUT"
    ```
  - Idempotency guard: `gh release view "$TAG" && echo "exists, skipping" && exit 0 || true` (continue-on-error step gating the publish).
  - Package: `gzip -k data/orphanet.sqlite`; `sha256sum data/orphanet.sqlite.gz > data/orphanet.sqlite.gz.sha256`; write `manifest.json` (version, date, counts, schema_version, build_utc) via a small python step.
  - Publish: `softprops/action-gh-release@v2` with `tag_name: ${{ steps.meta.outputs.tag }}`, `files: data/orphanet.sqlite.gz, data/orphanet.sqlite.gz.sha256, data/manifest.json`, `fail_on_unmatched_files: true`.
- [ ] **Step 2:** Validate YAML parses. Note in the PR description that the first run must be triggered via `workflow_dispatch` and that `data_resolver.release_repo` default must match this repo.
- [ ] **Step 3: Commit** `ci: build-data workflow (publish SQLite to GitHub Release)`.

### Task 23: Docs + router integration entry

**Files:** Create `README.md`, `AGENTS.md`, `CLAUDE.md`, `.env.example`, `docs/router/servers.yaml.snippet`.

- [ ] **Step 1:** Copy mondo-link `AGENTS.md` + `CLAUDE.md`; rewrite for Orphanet (two-plane boundary, the eight products, the artifact pipeline, definition-of-done). Write `README.md`: tool table (spec §8), quickstart (`make install`, `make data` or `make data-fetch`, `make dev`), MCP client setup, data provenance + CC BY 4.0 citation, the `data-fetch` vs `data` distinction.
- [ ] **Step 2:** Write `.env.example` with `ORPHANET_LINK_DATA__*` keys and a comment block; write `docs/router/servers.yaml.snippet` containing exactly the spec §14 entry plus the `GF_ORPHANET_URL` note (this is the prepared, not-pushed router integration).
- [ ] **Step 3:** Run `make ci-local` (full gate). **Step 4: Commit** `docs: README, AGENTS, CLAUDE, env example, router snippet`.

---

## Self-Review

**1. Spec coverage:**
- §4 products → Tasks 4–8 (one parser per product incl. classification). ✓
- §5 two planes → Tasks 1–13 (data plane) + 14–19 (mcp plane). ✓
- §7 schema → Task 2. ✓
- §8 tool surface (18 tools) → Tasks 15–18 (discovery 2, diseases 3, batch 2, associations 7, classification 3, xref 2 = 19 registrations incl. find_* under associations). ✓
- §9 resources, §10 envelope → Task 14. ✓
- §11 artifact publishing → Task 13 (runtime fetch + fallback) + Task 22 (build/publish workflow) + Task 20 (entrypoint). ✓
- §12 testing → fixtures/conftest in Task 19, TDD throughout, invariant tests in Task 14. ✓
- §13 packaging/ops → Task 1 + Task 20. ✓
- §14 router → Task 23. ✓
- §15 risks (specialty-id drift) → Task 3 specialties + Task 8 confirm-from-sample. ✓

**2. Placeholder scan:** Copy-and-rename tasks name the exact source file and the rename map (concrete). The single genuine "confirm at implementation time" is product3's exact tag names (Task 8 Step 1) — flagged because it is the one product not fetched during planning; every other parser has verified element names and real code.

**3. Type consistency:** payload key `orpha_code` (not `mondo_id`) used consistently in repository, services, tools, schemas; `orphanet_version` is the record/meta version key; `OrphanetService`/`get_orphanet_service` consistent across service_adapters, facade, tools, conftest; release asset name `orphanet.sqlite.gz` consistent across Task 13 (fetch), Task 20 (entrypoint), Task 22 (publish).

## Parallelization map (for subagent-driven execution)

- **Wave A (serial foundation):** Task 1 → Task 2 → Task 3.
- **Wave B (parallel parsers, after Task 2/3):** Tasks 4, 5, 6, 7, 8 are independent (separate files + fixtures) — dispatch concurrently with worktree isolation; each TDD-self-contained.
- **Wave C (serial):** Task 9 (builder, needs all parsers) → Task 10 (CLI).
- **Wave D (parallel after Task 9):** Task 11 (repository) ∥ Task 13 (data_resolver, independent of repository). Then Task 12 (services, needs repository).
- **Wave E (after Task 14):** Tasks 15, 16, 17, 18 (tool groups) are independent — dispatch concurrently; then Task 19 wires them.
- **Wave F (parallel):** Tasks 20, 21, 22, 23 are independent — dispatch concurrently.
