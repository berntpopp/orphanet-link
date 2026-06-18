# orphanet-link

A read-only [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server
that grounds rare-disease queries in **Orphanet's scientific knowledge files**
([Orphadata](https://www.orphadata.com/)).

It is backed by a local SQLite/FTS5 database built from the English Orphadata XML
products (nomenclature, cross-references, classifications, gene associations, HPO
phenotypes, epidemiology, and natural history). The database is built in CI and
published to GitHub Releases as a versioned artifact; the server downloads the
prebuilt database at runtime and falls back to building locally.

> **Status:** under active development. See `docs/superpowers/specs/` and
> `docs/superpowers/plans/` for the design and implementation plan.

## Data source & license

Data © Orphanet / INSERM, distributed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See the design spec for
the required citation. Research use only; not clinical decision support.
