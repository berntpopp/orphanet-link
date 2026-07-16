# Data & the build pipeline

How `orphanet-link` gets its data, how it stays fresh, and what you may do with it.

## Source: Orphadata

**Orphadata** is the free-access scientific-knowledge file distribution of
[Orphanet](https://www.orpha.net/) (INSERM, Paris). Base URL:
`https://www.orphadata.com/data/xml/` (`ORPHANET_LINK_DATA__BASE_URL`).

Eight English XML products are ingested. All are **directly downloadable with no
authentication and no registration**; a full local build downloads roughly 150 MB.

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

Which parser owns which product, and which tables each populates, is documented in
[`AGENTS.md`](../AGENTS.md).

## Licence & attribution

Orphadata are distributed under **Creative Commons Attribution 4.0 International
(CC BY 4.0)**. Redistributing a *derived* SQLite database is explicitly permitted
under CC BY 4.0 provided attribution is given and changes are indicated.

Required citation (also served by the `orphanet://citation` resource):

> "Orphadata Science: Free access data from Orphanet. © INSERM 1999.
> Available on http://sciences.orphadata.com/. Data version [date/version]."
> Changes: "Converted Orphadata XML to a normalized SQLite database."

This derived database is **not an official Orphanet product** and has not been
validated by Orphanet or INSERM.

## Getting the database

### Option A — prebuilt artifact (default, fastest)

Local development auto-fetches the latest prebuilt `orphanet.sqlite.gz` from the
GitHub Release on first startup when `ORPHANET_LINK_DATA__PREFER_PREBUILT=true`
(the default) and `ORPHANET_LINK_DATA__AUTO_BOOTSTRAP=true` (the default). No
manual step is required. Production uses its hardened init sidecar to fetch the
specific pinned release, verify its declared SHA-256, and materialize the
read-only application snapshot.

To force a fetch up front:

```bash
make data-fetch          # = uv run orphanet-link-data fetch
```

### Option B — build locally from Orphadata XML

Downloads all eight XML products (~150 MB) and builds the normalized SQLite
database locally:

```bash
make data                # = uv run orphanet-link-data build
```

### Inspect and refresh

```bash
make data-status         # = uv run orphanet-link-data status   (loaded release + counts)
make data-refresh        # = uv run orphanet-link-data refresh  (rebuild only if upstream changed)
```

`refresh` is conditional: the downloader issues a conditional GET (ETag /
Last-Modified) per product and rebuilds only when an upstream file actually
changed. It is the cron entry point.

### Example build stats

A typical build from a recent Orphanet release produces:

| Table | Count |
|---|---|
| Disorders (nomenclature) | 11,456 |
| Cross-references | 50,128 |
| HPO phenotype annotations | 115,878 |
| Gene associations | 4,552 |
| Prevalence records | 16,657 |

## The artifact pipeline

**CI (`.github/workflows/build-data.yml`)** builds the database and publishes it
to GitHub Releases:

- **Triggers:** weekly schedule (Orphanet releases are bi-annual, so a weekly
  check catches a new release within a week), `workflow_dispatch`, and any push
  touching `orphanet_link/ingest/**`.
- **Steps:** build → read `meta.orphanet_version` → compute the tag
  `data-<version>` → exit early if a Release for that tag already exists
  (idempotent) → gzip → write `.sha256` + `manifest.json` → create the Release.

**Runtime (`services/data_resolver.py`)**, on local/development server start with
`AUTO_BOOTSTRAP=true`:

1. If `DATA__PREFER_PREBUILT=true`: fetch the latest `data-*` Release asset
   (`orphanet.sqlite.gz`) → **verify sha256** → decompress into the data dir →
   validate `meta.schema_version` compatibility.
2. On any failure (offline, missing asset, schema mismatch): fall back to a full
   local build.

An incompatible prebuilt database triggers a local rebuild rather than a crash.
Pin a specific release with `ORPHANET_LINK_DATA__RELEASE_TAG=data-<version>`; see
[Configuration](configuration.md). Production calls `orphanet-link-data fetch`
from its init sidecar, with both this release tag and its immutable
`DATA__BUNDLE_EXPECTED_SHA256` configured; it does not fall back to a local build.
