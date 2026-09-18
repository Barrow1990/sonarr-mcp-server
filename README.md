# sonarr-mcp-server

A minimal [Model Context Protocol](https://modelcontextprotocol.io) server that
connects to [Sonarr](https://sonarr.tv), packaged for Docker.

It lets an MCP-compatible assistant (Claude Code, Claude Desktop, etc.) browse
your TV library, check for missing episodes, look up new series, and trigger
downloads — without giving it direct access to Sonarr's API key or network.

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

## Configuration

Set two environment variables (see `.env.example`):

- `SONARR_URL` — e.g. `http://192.168.1.50:8989`
- `SONARR_API_KEY` — Sonarr > Settings > General > API Key

## Running with Docker

Build the image:

```bash
docker build -t sonarr-mcp-server .
```

This server speaks MCP over **stdio**, not HTTP — there's no port to publish.
An MCP client spawns the container itself and talks to it over stdin/stdout,
so the usual pattern is to register it directly with your client rather than
leaving a container running in the background.

### Claude Code

```bash
claude mcp add sonarr -s user -- docker run -i --rm \
  -e SONARR_URL=http://192.168.1.50:8989 \
  -e SONARR_API_KEY=your-api-key \
  sonarr-mcp-server
```

### Claude Desktop

Add to your MCP server config:

```json
{
  "mcpServers": {
    "sonarr": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "SONARR_URL=http://192.168.1.50:8989",
        "-e", "SONARR_API_KEY=your-api-key",
        "sonarr-mcp-server"
      ]
    }
  }
}
```

### docker-compose

`docker-compose.yml` is included as a convenience for building the image and
keeping `SONARR_URL`/`SONARR_API_KEY` in a `.env` file — copy `.env.example`
to `.env` and fill it in, then `docker compose build`. It is not meant to be
left running as a persistent service; the container an MCP client actually
talks to is the one it spawns itself via `docker run -i`, per above.

## Running without Docker

```bash
pip install -r requirements.txt
SONARR_URL=http://192.168.1.50:8989 SONARR_API_KEY=your-api-key python server.py
```

## License

MIT
