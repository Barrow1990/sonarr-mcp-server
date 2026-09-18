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
| `GET /ready` | `SONARR_URL` is reachable, `SONARR_API_KEY` is accepted (via Sonarr's `/system/status`), *and* `SONARR_API_VERSION` is still an API version Sonarr serves (see [API version checking](#api-version-checking)). | `200 {"status": "ok", "reachable": true, "authenticated": true, "sonarr": {...}, "apiVersion": {...}}` | `503 {"status": "error", "reachable": ..., "authenticated": ..., "error": "..."}` |

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
| `SONARR_API_VERSION` | no | `v3` | Sonarr REST API version to call (`/api/<version>/...`) |
| `MCP_HOST` | no | `0.0.0.0` | Interface the server binds to inside the container |
| `MCP_PORT` | no | `8931` | Port the server listens on |
| `MCP_AUTH_TOKEN` | no | — | Shared secret required as `Authorization: Bearer <token>`. Unset = no auth (see above) |

### API version checking

Sonarr exposes an unauthenticated, unversioned `GET /api` endpoint that
reports which API version is current and which are deprecated (e.g.
`{"current": "v3", "deprecated": []}` — see
[`ApiInfoController`](https://github.com/Sonarr/Sonarr/blob/develop/src/Sonarr.Http/ApiInfoController.cs)
in Sonarr's source). `GET /ready` calls it and compares it against
`SONARR_API_VERSION`:

- version matches `current`, or is listed under `deprecated` (still served,
  just on notice) → healthy, reported under the response's `apiVersion` key.
- version isn't offered at all any more → `503`, since every tool call
  would otherwise start failing with 404s. Bump `SONARR_API_VERSION` to
  match what Sonarr now reports.
- Sonarr doesn't have this endpoint (very old versions) or it's
  unreachable → non-fatal, `apiVersion: {"checked": false}`.

This turns a silent break on a Sonarr upgrade into a readiness-probe
failure instead.

## Image

Built and pushed to `ghcr.io/barrow1990/sonarr-mcp-server` by
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) on every push to
`master` that passes tests, tagged `:latest`, `:<commit-sha>`, and
`:sonarr-<api-version>` (e.g. `:sonarr-v3` — the Sonarr API version this
build targets, read out of `server.py`'s `SONARR_API_VERSION` default so it
can't drift from what the code actually calls). `docker-compose.yml` pulls
`:latest` by default; swap in `build: .` there instead if you'd rather build
locally from the `Dockerfile`.

The image is a two-stage build (`python:3.12-alpine` compiling dependencies
into `--target=/deps` with no bytecode cache, then a fresh `python:3.12-alpine`
stage that copies just those library files and drops pip/setuptools/wheel
entirely) and runs as a non-root user. All dependencies — including
`cryptography`'s compiled `cffi` extension — ship musllinux wheels, so the
alpine base needs no compiler at build time. This keeps the published image
around 125MB, less than half the `python:3.12-slim` equivalent. Dependencies
in `requirements.txt` are pinned to exact versions rather than `>=` ranges,
so a routine `docker build` can't silently pull in a heavier resolution than
the one that was actually tested.

## Running with Docker Compose

```bash
cp .env.example .env   # fill in SONARR_URL / SONARR_API_KEY
docker compose up -d --pull always
```

The server is then reachable at `http://<docker-host>:8931/mcp` from anything
on your internal network.

## Managing with Dockhand

Point Dockhand at `ghcr.io/barrow1990/sonarr-mcp-server` and let it track new
tags — this is the registry-pull model Dockhand's image-update tracking
(Grype/Trivy scans, tag tracking, scheduled updates) is actually built around.
The alternative, pointing Dockhand at this repo as a Git-deployed Compose
stack with `build: .`, works too, but syncing new Git commits does **not**
imply rebuilding the image — those are two separate steps for a build-from-
source stack, which is exactly what caused the stale-container issues this
project hit early on (see commit history). The registry model sidesteps that
class of bug entirely: "new tag available" and "pull + recreate" are one
action.

**Make the GHCR package public**, or every pull will need `docker login
ghcr.io` with a PAT on each deploy host — a private package by default
requires auth even to `docker pull`, which most homelab boxes won't have
configured.

Set a restart policy of `unless-stopped` (already in `docker-compose.yml`) so
Dockhand-driven restarts and host reboots bring it back up without manual
intervention. The `HEALTHCHECK` in the `Dockerfile` (`GET /health`) drives
Docker's/Dockhand's container health status; use `GET /ready` (see above)
separately if you want to alert on Sonarr connectivity specifically rather
than container liveness.

**Environment variables in Dockhand**: `docker-compose.yml` loads
`SONARR_URL`/`SONARR_API_KEY`/`MCP_AUTH_TOKEN` via `env_file: [.env, .env.dockhand]`
(both optional; `.env.dockhand` loads second, so it wins for any key it also
sets). This is deliberate — a Git-deployed stack's `.env` is whatever's
checked out from the repo (i.e. `.env.example`'s placeholders, since real
`.env` is gitignored and not committed), while Dockhand writes the values you
configure in its UI to `.env.dockhand` instead. If you set `SONARR_URL` in
Dockhand's UI and the container is still using a placeholder, check that
Dockhand is actually writing to `.env.dockhand` in the stack directory (not
some other file) and that a rebuild has run since — a synced Git file change
alone doesn't rebuild the image; see `GET /ready` to confirm what's live.

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

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

- `tests/test_tools.py` — each tool's logic against a mocked Sonarr
  (`httpx.MockTransport`, no extra mocking library needed).
- `tests/test_http.py` — `/health`, `/ready`, and the bearer-auth middleware,
  via `server.build_app()` (the exact app `__main__` runs) through Starlette's
  `TestClient`.
- `tests/test_live_sonarr.py` — **opt-in** contract tests against a real
  Sonarr instance, to catch drift if a Sonarr upgrade renames/removes a field
  these tools depend on (`id`, `title`, `statistics.percentOfEpisodes`,
  `tvdbId`, `version`, ...). Skipped by default (no Sonarr in CI); run with:
  ```bash
  RUN_LIVE_SONARR_TESTS=1 SONARR_URL=https://sonarr.example.com \
  SONARR_API_KEY=<real key> python -m pytest tests/test_live_sonarr.py -v
  ```

CI (`.github/workflows/ci.yml`) runs the mocked suite on every push/PR; the
GHCR build only runs after it passes.

## License

MIT
