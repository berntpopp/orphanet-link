# Architecture & the MCP surface

What a client sees: the response envelope, the response modes, the resources, and
the error taxonomy. For the *internal* boundaries (the two planes, the parser
layout, the determinism contract, the package tree) see [`AGENTS.md`](../AGENTS.md).

## Shape of the server

A read-only **SQLite + FTS5** index, built from the eight Orphadata XML products
(see [Data](data.md)), fronted by an MCP tool layer. There is no live Orphanet API
call on the request path: every tool answers from the local index, so latency is a
local query and the answer is reproducible against a stated Orphanet release.

## Response envelope

Every tool follows the fleet **Response-Envelope-Standard-v1**: a flat
`success` / `_meta` / payload-or-error frame. Errors are **returned**, never raised
to the client.

`_meta.next_commands` carries ready-to-call follow-up suggestions in `compact` and
richer modes. Follow them rather than guessing the next tool.

## Response modes

Every tool accepts `response_mode` ∈ `minimal | compact | standard | full`
(default **`compact`**). It is the primary token-cost knob.

| Mode | Body | `_meta` keys |
|---|---|---|
| `minimal` | identity anchors only | `tool, request_id, source, data_version` |
| `compact` (default) | null/empty dropped recursively; search hits get a snippet | `+ next_commands, capabilities_version` |
| `standard` | full record | `+ elapsed_ms` |
| `full` | full record | `+ elapsed_ms` |

The verbose human-readable `orphanet_version` string ships only in `standard` /
`full`; the lean modes ground the call with the short `_meta.data_version` hash
instead.

`compact`+ echoes `capabilities_version` — a content hash of the discovery contract
— so a warm client can skip re-fetching `get_server_capabilities`.

**Prefer one call over a fan-out:** `get_disease(term, include=['genes',
'phenotypes','prevalence','disability'])` composes the association sections into a
single record instead of four round-trips.

List tools carry a pagination block (`total` / `returned` / `limit` / `offset` /
`truncated` / `next_offset`); when truncated, `_meta.next_commands` offers the
forward-page step. Ordering is a stable, tested contract — see `AGENTS.md`.

## Error taxonomy

Seven codes: `invalid_input`, `not_found`, `ambiguous_query`, `data_unavailable`,
`rate_limited`, `upstream_unavailable`, `internal_error`.

## Resources

The server exposes MCP resources under the `orphanet://` scheme:

| URI | Contents |
|---|---|
| `orphanet://capabilities` | Full discovery contract (JSON) |
| `orphanet://tools` | Live tool overview (JSON) |
| `orphanet://citation` | Required INSERM attribution string, stamped with the loaded release |
| `orphanet://research-use` | Research-use-only statement |
| `orphanet://usage` | Usage guide |
| `orphanet://reference` | Reference links |

The CC BY 4.0 licence and the required attribution are carried in the
`get_server_capabilities` payload (`license`, `recommended_citation`) and by
`orphanet://citation`.

## Where the research-use warning lives

A deliberate design divergence, and a contract tested in
`tests/unit/test_docs_and_ci_contracts.py`: the research-use restriction is
surfaced through **discovery** — `get_server_capabilities` (`research_use_only`,
`research_use_notice`), `orphanet://research-use`, `orphanet://capabilities`, and
the project documentation.

Ordinary tool payloads do **not** carry a per-call `unsafe_for_clinical_use` field.
The warning is a property of the server, not of each row; stamping every payload
would cost tokens on every call without telling a client anything the capabilities
contract has not already told it.

## Typical workflow

```
resolve_disease(query="Aicardi syndrome")
  -> get_disease(term="ORPHA:676")
      -> get_disease_genes / get_disease_phenotypes / get_disease_prevalence
      -> get_disease_classification / get_disease_ancestors
      -> map_cross_ontology
```
