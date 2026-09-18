# sonarr-mcp-server

A minimal [Model Context Protocol](https://modelcontextprotocol.io) server that
connects to [Sonarr](https://sonarr.tv), packaged for Docker.

It runs as a standing network service (streamable-http transport, not stdio),
so any MCP client on your internal network can connect to
`http://<host>:<port>/mcp` — the container isn't spawned per-client, and
container lifecycle/updates can be handed off to a tool like
[Dockhand](https://dockhand.pro).

## Tools

| Tool | Description |
|---|---|
| `list_series` | List series in the library, optionally filtered by title |
| `series_details` | Full details for one series by ID |
| `missing_episodes` | Missing/wanted episodes, optionally scoped to one series |
| `lookup_series` | Search for new series by title (does not add them) |
| `search_series` | Trigger a search for missing episodes of a series already in the library |
| `system_status` | Sonarr system status, disk space, and health checks |

`search_series` is the only tool that changes state in Sonarr (it kicks off a
real search/download). Everything else is read-only.

## Health endpoints

Two plain HTTP endpoints, reachable without `MCP_AUTH_TOKEN` (so Docker's
`HEALTHCHECK`, Dockhand, or any other monitor can poll them without the
secret):

| Endpoint | Checks | Healthy | Unhealthy |
|---|---|---|---|
| `GET /health` | The process is up and serving HTTP. Does **not** call Sonarr. | `200 {"status": "ok"}` | (doesn't respond) |
| `GET /ready` | `SONARR_URL` is reachable *and* `SONARR_API_KEY` is accepted, by calling Sonarr's own `/system/status`. | `200 {"status": "ok", "reachable": true, "authenticated": true, "sonarr": {"url": ..., "version": ...}}` | `503 {"status": "error", "reachable": ..., "authenticated": ..., "error": "..."}` |

They're split deliberately: `/health` is what the container's own
`HEALTHCHECK` uses (so a transient Sonarr outage doesn't get the container
itself restarted in a loop), while `/ready` is for verifying config — after
changing `SONARR_URL`/`SONARR_API_KEY`, `curl http://<host>:8931/ready` tells
you plainly whether the host is reachable, the key is valid, or both.

## Authentication

Set `MCP_AUTH_TOKEN` (a random shared secret — `openssl rand -hex 32`) and
every request must carry `Authorization: Bearer <token>` or the server
returns `401`. This is checked by a small Starlette middleware in front of
the MCP app, **not** the `mcp` SDK's built-in OAuth support
(`mcp.server.auth`) — that machinery expects a full OAuth authorization
server (issuer/resource metadata, RFC 8414/8707/9068 discovery), which is
unnecessary complexity for one secret shared by trusted LAN clients.

Leave `MCP_AUTH_TOKEN` unset and the server runs with **no auth** — anything
that can reach `http://<host>:<port>/mcp` can call every tool, including
`search_series`. The server logs a warning on startup when it's running this
way. Either way, the trust boundary is still the network:

- **Do not** publish this port through any reverse proxy, port-forward, or
  anything else reachable from outside your LAN/VLAN — the bearer token
  protects against anyone *on* the network, not against the open internet.
- Bind the compose `ports:` mapping to a specific internal interface (e.g.
  `192.168.1.50:8931:8931`) rather than all interfaces, if you want to be
  stricter about which hosts on your network can reach it at all.

## Configuration

Environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `SONARR_URL` | yes | — | e.g. `http://192.168.1.50:8989` |
| `SONARR_API_KEY` | yes | — | Sonarr > Settings > General > API Key |
| `MCP_HOST` | no | `0.0.0.0` | Interface the server binds to inside the container |
| `MCP_PORT` | no | `8931` | Port the server listens on |
| `MCP_AUTH_TOKEN` | no | — | Shared secret required as `Authorization: Bearer <token>`. Unset = no auth (see above) |

## Running with Docker Compose

```bash
cp .env.example .env   # fill in SONARR_URL / SONARR_API_KEY
docker compose up -d --build
```

The server is then reachable at `http://<docker-host>:8931/mcp` from anything
on your internal network.

## Managing with Dockhand

Point Dockhand at this repo as a Compose stack (Git-deploy) to pull, build,
and redeploy automatically when this repo updates, or build/push the image to
a registry and let Dockhand track new tags — either flow works since the
container just needs to keep listening on `MCP_PORT`. Set a restart policy of
`unless-stopped` (already in `docker-compose.yml`) so Dockhand-driven restarts
and host reboots bring it back up without manual intervention. The
`HEALTHCHECK` in the `Dockerfile` (`GET /health`) drives Docker's/Dockhand's
container health status; use `GET /ready` (see above) separately if you want
to alert on Sonarr connectivity specifically rather than container liveness.

## Connecting a client

### Claude Code

```bash
claude mcp add sonarr -s user --transport http http://<docker-host>:8931/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```
(Drop the `--header` flag if you're running with `MCP_AUTH_TOKEN` unset.)

### Claude Desktop

Claude Desktop's built-in config expects a locally-spawned `command`, so for
a network server like this you'll need an HTTP-to-stdio bridge such as
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "sonarr": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "http://<docker-host>:8931/mcp",
        "--header", "Authorization: Bearer <MCP_AUTH_TOKEN>"
      ]
    }
  }
}
```

## Running without Docker

```bash
pip install -r requirements.txt
SONARR_URL=http://192.168.1.50:8989 SONARR_API_KEY=your-api-key \
MCP_AUTH_TOKEN=your-shared-secret python server.py
```

## License

MIT
