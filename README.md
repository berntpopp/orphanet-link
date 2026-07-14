# orphanet-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/orphanet-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/orphanet-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/orphanet-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/orphanet-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A read-only [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that grounds
rare-disease questions in **Orphanet's scientific knowledge files**
([Orphadata](https://www.orphadata.com/), INSERM), served from a locally-built SQLite + FTS5 index
of the eight English Orphadata XML products.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

Orphadata ships its rare-disease knowledge as eight separate bulk XML products — nomenclature,
cross-references, ~33 per-specialty classification files, gene associations, HPO phenotypes,
epidemiology, natural history, functional consequences. They are a **download, not a query
surface**: asking "which genes are linked to Aicardi syndrome, what is its prevalence, and what is
it called in OMIM?" means fetching ~150 MB of XML, joining four products on ORPHAcode, and walking
a poly-hierarchy by hand.

`orphanet-link` does that join once — into a normalized, read-only SQLite + FTS5 index with
precomputed classification closures — and serves it as MCP tools. A free-text label, a synonym, a
bare ORPHA code, or an external CURIE (OMIM, MONDO, ICD-10/11, UMLS, GARD, MeSH, MedDRA) all
resolve to the same canonical disorder, and every answer is reproducible against a stated Orphanet
release.

## Quick start

The GeneFoundry instance is hosted — no install:

```bash
claude mcp add --transport http orphanet-link https://orphanet-link.genefoundry.org/mcp
```

Locally (Python 3.12+ and [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/berntpopp/orphanet-link.git
cd orphanet-link
uv sync --group dev
make data-fetch     # pull the prebuilt SQLite index from the GitHub Release
make dev            # unified REST + MCP → http://127.0.0.1:8000/mcp
claude mcp add --transport http orphanet-link http://127.0.0.1:8000/mcp
```

The server needs a database before it can answer. `make data-fetch` pulls the prebuilt one
published by CI; `make data` builds it from the Orphadata XML instead (~150 MB). Either way the
server also bootstraps one on first start when none is present — see [Data](docs/data.md).

`make dev` runs `--transport unified`, the **only** mode that serves MCP; `--transport http` is
REST/health-only. `make docker-up` runs the container stack and prints its MCP URL. See
[Deployment](docs/deployment.md).

## Tools

Every tool is read-only, accepts `response_mode` (`minimal` / `compact` / `standard` / `full`,
default `compact`), and returns the fleet's `success` / `_meta` / payload-or-error envelope.
`_meta.next_commands` carries ready-to-call follow-ups — see
[Architecture & the MCP surface](docs/architecture.md).

| Tool | Purpose |
|---|---|
| `get_server_capabilities` | Discovery: tool signatures, response modes, workflows, error taxonomy, limits, Orphanet release |
| `get_diagnostics` | Index status: Orphanet release, disorder counts, schema version, build time, runtime metrics |
| `resolve_disease` | Free-text label, synonym, ORPHA code (`ORPHA:166024` or `166024`), or external xref CURIE → canonical `{orpha_code, name, match_type}` |
| `search_diseases` | FTS over disease names and synonyms; relevance-ranked, paginated, optional obsolete inclusion |
| `get_disease` | Full disorder record: type/group, synonyms, grouped cross-references, classification parents/children, association counts; sparse `fields` projection |
| `get_disease_genes` | Gene associations: symbol, HGNC id, association type and status, source PMIDs, gene xrefs |
| `get_disease_phenotypes` | HPO annotations: HPO id, term name, frequency category; optional frequency filter |
| `get_disease_prevalence` | Epidemiology: prevalence type, class band, numeric ValMoy, geography, validation status, source |
| `get_disease_natural_history` | Age-of-onset categories and inheritance patterns |
| `get_disease_disability` | Functional-consequence annotations: ability categories affected and severity grades |
| `get_disease_classification` | Immediate parents and children in Orphanet's poly-hierarchical classification trees |
| `get_disease_ancestors` | Transitive classification ancestors (precomputed closure), paginated |
| `get_disease_descendants` | Transitive classification descendants (precomputed closure), paginated |
| `map_cross_ontology` | A disorder's cross-references grouped by source (OMIM, MONDO, ICD-10/11, UMLS, GARD, MeSH, MedDRA) with mapping relations |
| `resolve_xref` | External CURIE → matching Orphanet disorder(s), paginated |
| `find_diseases_by_gene` | Reverse lookup: HGNC gene symbol → associated disorders, paginated |
| `find_diseases_by_phenotype` | Reverse lookup: HPO term id → associated disorders, paginated |
| `resolve_disease_batch` | Batch-resolve up to `MAX_BATCH_ITEMS` labels/codes/xrefs; partial success per item |
| `get_disease_batch` | Batch-fetch up to `MAX_BATCH_ITEMS` disease records; partial success per item; sparse `fields` projection |

Leaf names are intentionally **unprefixed**, per the fleet's Tool-Naming Standard v1. Behind
[genefoundry-router](https://github.com/berntpopp/genefoundry-router) this server mounts under the
`orphanet` namespace, so tools surface as `orphanet_<tool>` — e.g. `orphanet_resolve_disease`, the
pinned entry point.

## Data & provenance

**Source** — [Orphadata](https://www.orphadata.com/), the free-access scientific-knowledge file
distribution of Orphanet (INSERM, Paris). Eight English XML products, downloaded directly with no
authentication.

**Refresh** — Orphanet releases bi-annually. CI rebuilds the index weekly and publishes it as a
versioned `data-<release>` GitHub Release (`orphanet.sqlite.gz`); the server fetches that artifact,
verifies its sha256, and falls back to a local build when it is unavailable. `make data-status`
prints the loaded release. Details: [Data & the build pipeline](docs/data.md).

**Licence** — Orphadata are **CC BY 4.0**. Redistributing a *derived* SQLite database is explicitly
permitted provided attribution is given and changes are indicated.

**Required citation** — also served by the `orphanet://citation` resource:

> "Orphadata Science: Free access data from Orphanet. © INSERM 1999.
> Available on http://sciences.orphadata.com/. Data version [date/version]."
> Changes: "Converted Orphadata XML to a normalized SQLite database."

This derived database is **not an official Orphanet product** and has not been validated by
Orphanet or INSERM.

## Documentation

- [Data & the build pipeline](docs/data.md) — the eight Orphadata products, the data CLI, licensing, and the CI artifact pipeline.
- [Deployment](docs/deployment.md) — transports (and the `--transport http` footgun), Docker, the Host/Origin/CORS boundary, router integration, deploy verification.
- [Configuration](docs/configuration.md) — the `ORPHANET_LINK_*` variables; [`.env.example`](.env.example) is the exhaustive annotated reference.
- [Architecture & the MCP surface](docs/architecture.md) — response envelope, response modes, `orphanet://` resources, error taxonomy, and where the research-use warning lives.
- [`AGENTS.md`](AGENTS.md) — engineering conventions: the two planes, invariants, the determinism contract, package layout.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.

## Contributing

See [`AGENTS.md`](AGENTS.md) for the conventions and the definition of done. `make ci-local` is the
gate — format, lint, line budget, README standard, action pins, mypy, and tests — and it must be
green before merge.

## License

Code: [MIT](LICENSE) © 2026 Bernt Popp.

Data: Orphadata is **CC BY 4.0** © INSERM 1999 — attribution required and changes indicated, as
stated under [Data & provenance](#data--provenance).
