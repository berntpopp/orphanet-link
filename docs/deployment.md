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

On first boot the entrypoint bootstraps the database (prebuilt fetch, falling back
to a local build); see [Data](data.md). A bootstrap failure there is non-fatal —
the app lifespan retries on startup.

Overlays: `docker/docker-compose.prod.yml` (hardened production) and
`docker/docker-compose.npm.yml` (Nginx Proxy Manager). Backends are
**unauthenticated by design** and must be reachable only through the router or a
reverse proxy — never published directly to the internet.

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
