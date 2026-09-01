# Deployment

Running `orphanet-link` locally, in Docker, and behind the GeneFoundry router.

## Transports (read this first)

`server.py --transport` selects the surface. The modes are **not** interchangeable:

| Mode | Serves | MCP at `/mcp`? |
|---|---|---|
| `unified` (default) | FastAPI REST/`/health` **and** MCP over Streamable HTTP | **yes** |
| `http` | FastAPI REST only (`/health` + service metadata) | **no** |
| `stdio` | MCP over stdin/stdout, for direct client use | n/a |

> [!WARNING]
> `--transport http` is REST/FastAPI-only. It is **not** MCP-over-HTTP and does not
> expose the MCP endpoint. **Router deployments must run `--transport unified`** and
> point the router URL at the `/mcp` endpoint.

## Local

```bash
make dev          # unified REST + MCP, auto-reload → http://127.0.0.1:8000/mcp
make mcp-serve    # stdio MCP server (uv run python mcp_server.py)
```

## Docker

```bash
make docker-build
make docker-up     # starts the stack, then prints the MCP URL
make docker-url    # print the MCP + health URLs of the running container
make docker-logs
make docker-down
```

The container publishes on **loopback only**:
`127.0.0.1:${ORPHANET_LINK_HOST_PORT:-8000}:8000`. Set `ORPHANET_LINK_HOST_PORT`
in `docker/.env` to move it off 8000 (useful when sibling `-link` projects are
running). Because the host port is therefore not fixed, `make docker-up` prints
the resulting MCP URL rather than assuming one.

The base Compose file is for local development and enables an in-process bootstrap
(prebuilt fetch, falling back to a local build); see [Data](data.md). Production
uses the hardened `orphanet-data-init` sidecar to fetch and verify the release
pinned in `container-release.json`. The application waits for that service to
complete successfully, mounts its versioned read-only snapshot, and has no
in-process bootstrap path or write access to the data volume.

The current production data pin is
`data-1.3.42-4.1.8-2025-03-03-r20260623T075350Z-r2` with compressed bundle
digest `sha256:cc32164c7f64bfb053fabdb2c739ff0236cc039000d3827e7c64160d70dec62f`.
The expanded SQLite digest is
`sha256:d7408be62d055700901e635c1582c3ccdf5245e87b88f53c90f8fbdb2f284a53`.
See [Data](data.md#current-audited-production-snapshot) for the complete
release-asset identity set.

Overlays: `docker/docker-compose.prod.yml` (hardened production) and
`docker/docker-compose.npm.yml` (Nginx Proxy Manager; the same init-sidecar
boundary). Backends are
**unauthenticated by design** and must be reachable only through the router or a
reverse proxy — never published directly to the internet.

## Fleet deploy contract

`docker/docker-compose.npm.yml` is the file the GeneFoundry fleet controller
(`strato_v6_docker_npm`) deploys and validates: it renders the file with
`docker compose config --format json`, projects it, and refuses to author a
deployment record unless every application service declares the controller's
required security fields. Both services in this overlay — the run-once
`orphanet-data-init` sidecar and the `orphanet_link` app — declare an explicit
numeric `user: "999:999"`, this image's real uid:gid from `docker/Dockerfile`
(`useradd --system --gid app`); never copy this literal into a sibling repo,
the fleet runs mixed uids. `user` must **not** appear on the Compose files
listed in `container-release.json`'s `service.compose_files`
(`docker/docker-compose.yml`, `docker/docker-compose.prod.yml`) — the shared
release gate forbids it there.

As of `strato_v6_docker_npm` PR #41 the controller relaxed this contract
(`user`/`volumes` are optional-but-validated; `cpus` accepts a finite positive
float), so the init sidecar's integer `cpus: 1` (previously `"0.5"`) is no
longer strictly required — it is kept as-is.

Self-check against the controller's own projection before assuming a change
here deploys cleanly:

```bash
ORPHANET_LINK_IMAGE="ghcr.io/berntpopp/orphanet-link@sha256:<64 hex>" docker compose -f docker/docker-compose.npm.yml config --format json > /tmp/r.json
# from strato_v6_docker_npm:
uv run python -c "import sys,json; sys.path.insert(0,'scripts'); from utils.deployment_preflight import canonical_projection; canonical_projection(json.load(open('/tmp/r.json')), project='orphanet-link'); print('PROJECTION OK')"
```

## Host / Origin / CORS boundary

HTTP deployments enforce **exact** Host and Origin allowlists on every route.
Wildcards are not accepted.

- `ORPHANET_LINK_ALLOWED_HOSTS` — JSON list of exact `Host` values. Defaults to
  `["localhost","127.0.0.1","::1"]`. **Add the public reverse-proxy hostname** in
  production, or every proxied request is rejected.
- `ORPHANET_LINK_ALLOWED_ORIGINS` — the request-boundary policy for browser
  `Origin` headers (default `[]`).
- `ORPHANET_LINK_CORS_ORIGINS` — the CORS *response*-header policy.

`ALLOWED_ORIGINS` and `CORS_ORIGINS` are **separate policies and neither widens the
other**: a browser deployment must list its origin in *both*.

## MCP client setup

These HTTP examples target a server running `--transport unified`.

Claude Code, HTTP:

```bash
claude mcp add --transport http orphanet-link http://localhost:8000/mcp
```

Config block, HTTP:

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

Config block, stdio:

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

## Router integration

`orphanet-link` mounts into [`genefoundry-router`](https://github.com/berntpopp/genefoundry-router)
under the `orphanet` namespace. The registry entry and the router-side
`GF_ORPHANET_URL` variable are prepared in
[`router/servers.yaml.snippet`](router/servers.yaml.snippet). `GF_ORPHANET_URL` is
set on the **router** side, never in this repo's `.env`.

## Verifying a deploy

```bash
make verify-deploy URL=<server>/health
```

This pipes the live `/health` payload into `scripts/check_deployed_freshness.py`
and exits non-zero unless the running build's `git_sha` matches local HEAD — the
guard against a green local tree whose fixes never reached the running container.
