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

## ⚠️ No authentication

This server has no auth of its own — anything that can reach
`http://<host>:<port>/mcp` can call every tool, including `search_series`.
That's by design for a simple internal deployment, but it means the trust
boundary is entirely the network:

- **Do not** publish this port through any reverse proxy, port-forward, or
  anything else reachable from outside your LAN/VLAN.
- Bind the compose `ports:` mapping to a specific internal interface (e.g.
  `192.168.1.50:8931:8931`) rather than all interfaces, if you want to be
  stricter about which hosts on your network can reach it.
- If you later want to restrict *who* on the LAN can call it, put it behind
  something like a reverse proxy with IP allowlisting, or add auth to
  `server.py` — the `mcp` SDK supports `token_verifier`/OAuth on `MCPServer`.

## Configuration

Environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `SONARR_URL` | yes | — | e.g. `http://192.168.1.50:8989` |
| `SONARR_API_KEY` | yes | — | Sonarr > Settings > General > API Key |
| `MCP_HOST` | no | `0.0.0.0` | Interface the server binds to inside the container |
| `MCP_PORT` | no | `8931` | Port the server listens on |

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
and host reboots bring it back up without manual intervention.

## Connecting a client

### Claude Code

```bash
claude mcp add sonarr -s user --transport http http://<docker-host>:8931/mcp
```

### Claude Desktop

Claude Desktop's built-in config expects a locally-spawned `command`, so for
a network server like this you'll need an HTTP-to-stdio bridge such as
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "sonarr": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://<docker-host>:8931/mcp"]
    }
  }
}
```

## Running without Docker

```bash
pip install -r requirements.txt
SONARR_URL=http://192.168.1.50:8989 SONARR_API_KEY=your-api-key python server.py
```

## License

MIT
