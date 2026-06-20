# orphanet-link

A read-only [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server
that grounds rare-disease queries in **Orphanet's scientific knowledge files**
([Orphadata](https://www.orphadata.com/)).

It is backed by a locally-built, read-only **SQLite + FTS5** database parsed from
the eight English Orphadata XML products (nomenclature, cross-references,
classifications, gene associations, HPO phenotypes, epidemiology, and natural
history). The database is built in CI and published to GitHub Releases as a
versioned artifact; the server downloads the prebuilt database at runtime and
falls back to building locally when the artifact is unavailable.

`orphanet-link` is a sibling in the GeneFoundry "-link" fleet. It follows the
same two-plane architecture and conventions as `mondo-link` and slots into
`genefoundry-router` under the `orphanet` namespace.

> **Research use only.** This server is not clinical decision support. It is not
> suitable for diagnosis, treatment, triage, or patient management. The warning
> is surfaced through `get_server_capabilities`, `orphanet://research-use`,
> `orphanet://capabilities`, and this documentation; ordinary tool payloads do
> not carry a per-call `unsafe_for_clinical_use` field.

---

## Data source

**Orphadata** — the free-access scientific-knowledge file distribution of
[Orphanet](https://www.orpha.net/) (INSERM, Paris).

Eight English XML products are ingested; all are directly downloadable with no
authentication:

| Product | File | Contents |
|---|---|---|
| 1 | `en_product1.xml` | Nomenclature: name, synonyms, type, group, flags, cross-references (UMLS, OMIM, MONDO, ICD-10, ICD-11, GARD, MeSH, MedDRA) with mapping relation + validation status |
| 3 | `en_product3_<specialtyId>.xml` (~33 files) | Poly-hierarchical classification trees, one file per medical specialty |
| 4 | `en_product4.xml` | Disease-to-HPO associations with HPO frequency + optional diagnostic-criteria flag |
| 6 | `en_product6.xml` | Disorder-to-gene associations: symbol, type, locus, association type + status, source PMIDs; gene xrefs (HGNC, OMIM, Ensembl, UniProt, Genatlas, Reactome, ClinVar) |
| 7 | `en_product7.xml` | Linearisation: single non-redundant parent per disease |
| 8 (funct) | `en_funct_consequences.xml` | Disability annotations (Orphanet Functioning Thesaurus, ICF-CY-derived) |
| 9 prev | `en_product9_prev.xml` | Epidemiology: prevalence type, class band, ValMoy, geography, validation status, source |
| 9 ages | `en_product9_ages.xml` | Natural history: age-of-onset list + type-of-inheritance list |

### License & attribution

Data are distributed under **Creative Commons Attribution 4.0 International
(CC BY 4.0)**. Redistributing a derived SQLite database is explicitly permitted
under CC BY 4.0 provided attribution is given and changes are indicated.

Required citation (also available via `orphanet://citation`):

> "Orphadata Science: Free access data from Orphanet. © INSERM 1999.
> Available on http://sciences.orphadata.com/. Data version [date/version]."
> Changes: "Converted Orphadata XML to a normalized SQLite database."

---

## Install

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```bash
git clone https://github.com/berntpopp/orphanet-link.git
cd orphanet-link
uv sync --group dev   # installs all runtime + dev dependencies
```

---

## Build the database

### Option A — prebuilt artifact (default, fastest)

The server auto-fetches the latest prebuilt `orphanet.sqlite.gz` from the
GitHub Release on first startup when `ORPHANET_LINK_DATA__PREFER_PREBUILT=true`
(the default). No manual step is required.

To force a fetch manually:

```bash
make data-fetch
# equivalent to:
uv run orphanet-link-data fetch
```

### Option B — build locally from Orphadata XML

Downloads all eight XML products directly from Orphadata (~150 MB) and builds
the normalized SQLite database locally:

```bash
make data
# equivalent to:
uv run orphanet-link-data build
```

Check what is currently built:

```bash
make data-status
# equivalent to:
uv run orphanet-link-data status
```

Conditionally refresh (rebuild only if any upstream file changed):

```bash
make data-refresh
# equivalent to:
uv run orphanet-link-data refresh
```

### Example build stats

A typical build from a recent Orphanet release produces:

| Table | Count |
|---|---|
| Disorders (nomenclature) | 11,456 |
| Cross-references | 50,128 |
| HPO phenotype annotations | 115,878 |
| Gene associations | 4,552 |
| Prevalence records | 16,657 |

---

## Run the server

### Development (unified REST + MCP, auto-reload)

```bash
make dev
# equivalent to:
uv run python server.py --transport unified --host 127.0.0.1 --port 8000
```

The MCP endpoint is at `http://127.0.0.1:8000/mcp`.

Router deployments must run `--transport unified` and point the router URL at
the `/mcp` endpoint. The server's `--transport http` mode is REST/FastAPI-only
(`/health` and service metadata); it is not MCP-over-HTTP and does not expose
the MCP endpoint.

### stdio (for direct MCP client use)

```bash
make mcp-serve
# equivalent to:
uv run python mcp_server.py
```

### Docker

```bash
make docker-build
make docker-up     # binds a free host port; prints the MCP URL
make docker-logs   # follow container logs
make docker-down
```

---

## MCP client setup

These HTTP client examples target a server running `--transport unified`.

### Claude Code (HTTP transport)

```bash
claude mcp add --transport http orphanet-link http://localhost:8000/mcp
```

### MCP config block (HTTP)

```json
{
  "mcpServers": {
    "orphanet-link": {
      "transport": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Claude Code (stdio)

```json
{
  "mcpServers": {
    "orphanet-link": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "/path/to/orphanet-link"
    }
  }
}
```

---

## Tools (19 total)

All tools are `READ_ONLY_OPEN_WORLD`, accept `response_mode`
(`minimal` / `compact` / `standard` / `full`, default `compact`), and follow
the fleet's Response-Envelope-Standard-v1 (`success` / `_meta` / payload or
error). `_meta.next_commands` carries ready-to-call follow-up suggestions in
`compact` and richer modes.

| Tool | Purpose |
|---|---|
| `get_server_capabilities` | Discovery: tool list with signatures, response modes, workflows, error taxonomy, limits, Orphanet release |
| `get_diagnostics` | Index status: Orphanet release/version, disorder counts, schema version, build time, runtime metrics (request count, latency percentiles) |
| `resolve_disease` | Free-text label, synonym, ORPHA code (`ORPHA:166024` or `166024`), or external xref CURIE → canonical `{orpha_code, name, match_type}` |
| `search_diseases` | FTS over disease names and synonyms (relevance-ranked, paginated, optional obsolete inclusion) |
| `get_disease` | Full disorder record: type/group, synonyms, grouped cross-references, classification parents/children, counts of genes/phenotypes/prevalence; supports sparse `fields` projection |
| `get_disease_genes` | Gene-disease associations: gene symbol, HGNC id, association type, association status (Assessed / Not yet assessed), source PMIDs, gene xrefs |
| `get_disease_phenotypes` | HPO phenotype annotations: HPO id, term name, frequency category; optional filter by frequency label |
| `get_disease_prevalence` | Epidemiology records: prevalence type, class band, numeric ValMoy, geographic area, validation status, source reference |
| `get_disease_natural_history` | Natural history: age-of-onset categories and inheritance patterns |
| `get_disease_disability` | Functional consequence (disability) annotations: ability categories affected and severity grades |
| `get_disease_classification` | Immediate parents and children within Orphanet poly-hierarchical classification trees |
| `get_disease_ancestors` | Transitive classification ancestors (precomputed closure), paginated |
| `get_disease_descendants` | Transitive classification descendants (precomputed closure), paginated |
| `map_cross_ontology` | A disorder's cross-references grouped by source (OMIM, MONDO, ICD-10, ICD-11, UMLS, GARD, MeSH, MedDRA) with mapping relations; optional source filter |
| `resolve_xref` | External CURIE (OMIM/MONDO/ICD-10/ICD-11/UMLS/GARD/MeSH/MedDRA) → matching Orphanet disorder(s), paginated |
| `find_diseases_by_gene` | Reverse lookup: HGNC gene symbol → all associated Orphanet disorders, paginated |
| `find_diseases_by_phenotype` | Reverse lookup: HPO term id → all associated Orphanet disorders, paginated |
| `resolve_disease_batch` | Batch resolve up to `MAX_BATCH_ITEMS` labels/codes/xrefs in one call; partial success per item |
| `get_disease_batch` | Batch fetch up to `MAX_BATCH_ITEMS` disease records in one call; partial success per item; supports sparse `fields` projection |

### Typical workflow

```
resolve_disease(query="Aicardi syndrome")
  -> get_disease(term="ORPHA:676")
      -> get_disease_genes / get_disease_phenotypes / get_disease_prevalence
      -> get_disease_classification / get_disease_ancestors
      -> map_cross_ontology
```

Follow `_meta.next_commands` rather than guessing the next tool.

---

## Resources

The server exposes MCP resources under the `orphanet://` scheme:

- `orphanet://capabilities` — full discovery contract (JSON)
- `orphanet://tools` — live tool overview
- `orphanet://citation` — required INSERM attribution string
- `orphanet://license` — CC BY 4.0 text + required attribution + changes note
- `orphanet://research-use` — research-use-only statement
- `orphanet://usage` — usage guide
- `orphanet://reference` — reference links

---

## Development commands

```bash
make install        # uv sync --group dev
make format         # ruff format
make lint           # ruff check
make typecheck      # mypy --strict
make test           # pytest (unit only)
make test-cov       # pytest with coverage report
make ci-local       # format-check + lint-ci + lint-loc + typecheck + test-fast (the full gate)
make verify-deploy URL=<server>/health   # confirm deployed SHA matches local HEAD
```

---

## Disclaimer

This server is **for research use only**. It is **not** clinical decision support
and is **not** suitable for diagnosis, treatment, triage, or patient management.
Orphanet data are provided under CC BY 4.0 by INSERM; this derived database is
not an official Orphanet product and has not been validated by Orphanet or INSERM.
