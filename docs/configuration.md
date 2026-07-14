# Configuration

All settings are `pydantic-settings`-backed, use the **`ORPHANET_LINK_`** prefix, and
use `__` as the nesting delimiter (e.g. `ORPHANET_LINK_DATA__BASE_URL` sets
`data.base_url`).

[`.env.example`](../.env.example) is the **exhaustive, annotated reference** — every
variable with its default. Copy it to `.env` and adjust. This page is the map.

> `GF_ORPHANET_URL` is **not** an `orphanet-link` variable. It is set on the
> **router** side; see [Deployment → router integration](deployment.md).

## Server

| Variable | Default | Notes |
|---|---|---|
| `ORPHANET_LINK_HOST` | `127.0.0.1` | Use `0.0.0.0` for Docker / remote access. |
| `ORPHANET_LINK_PORT` | `8000` | |
| `ORPHANET_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. **`http` is REST-only — no MCP endpoint.** See [Deployment](deployment.md). |
| `ORPHANET_LINK_MCP_PATH` | `/mcp` | `unified` transport only. |
| `ORPHANET_LINK_RELOAD` | `false` | Uvicorn auto-reload; development only. |
| `ORPHANET_LINK_LOG_LEVEL` | `INFO` | `DEBUG` … `CRITICAL`. |
| `ORPHANET_LINK_LOG_FORMAT` | `console` | `console` \| `json` (log aggregators). |

## Request boundary

| Variable | Default | Notes |
|---|---|---|
| `ORPHANET_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | JSON list of **exact** `Host` values. Add the public proxy hostname in production. |
| `ORPHANET_LINK_ALLOWED_ORIGINS` | `[]` | Request-boundary `Origin` policy. |
| `ORPHANET_LINK_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS **response**-header policy. |

Origin validation and CORS are separate policies; neither widens the other. Full
semantics: [Deployment → Host / Origin / CORS](deployment.md).

## Data store (`ORPHANET_LINK_DATA__*`)

| Variable | Default | Notes |
|---|---|---|
| `DATA__DATA_DIR` | `<repo>/data` | Holds the SQLite database and the download cache. |
| `DATA__DB_FILENAME` | `orphanet.sqlite` | |
| `DATA__BASE_URL` | `https://www.orphadata.com/data/xml/` | Orphadata English XML files; no auth. |
| `DATA__DOWNLOAD_TIMEOUT` | `300` | Seconds. Large products (product4 ~50 MB) need the headroom. |
| `DATA__USER_AGENT` | `orphanet-link/<version> (+repo URL)` | Sent to Orphadata and GitHub. |

## Prebuilt artifact

| Variable | Default | Notes |
|---|---|---|
| `DATA__PREFER_PREBUILT` | `true` | Try the GitHub Release artifact before building locally. |
| `DATA__RELEASE_REPO` | `berntpopp/orphanet-link` | Host of the release assets. |
| `DATA__RELEASE_TAG` | `latest` | Resolves to the newest `data-*` release, or pin e.g. `data-1.3.42`. |
| `DATA__AUTO_BOOTSTRAP` | `true` | Ensure the database exists on first use. Set `false` only when managing the database lifecycle externally. |

See [Data](data.md) for the pipeline these knobs drive.

## In-process refresh scheduler (advanced; off by default)

Orphanet releases bi-annually, so refresh is better driven by the CI artifact
pipeline plus an external cron entry point (`make data-refresh`) than by an
in-process timer.

| Variable | Default | Notes |
|---|---|---|
| `DATA__REFRESH_ENABLED` | `false` | Background conditional refresh (`unified`/`http` only). |
| `DATA__REFRESH_INTERVAL_HOURS` | `168.0` | 7 days. |
| `DATA__REFRESH_JITTER_SECONDS` | `600` | Avoids a thundering herd across replicas. |
| `DATA__BUILD_LOCK_TIMEOUT` | `1800` | Seconds to wait for the cross-process build lock. |

## Query cache

| Variable | Default | Notes |
|---|---|---|
| `DATA__CACHE_SIZE` | `1024` | Max entries; `0` disables caching. |
| `DATA__CACHE_TTL` | `3600` | Seconds. |
