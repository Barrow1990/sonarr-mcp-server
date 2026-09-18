"""
Sonarr MCP Server

Exposes a small set of Sonarr (TV library manager) operations as MCP tools,
so an MCP-compatible AI assistant (e.g. Claude Code / Claude Desktop) can
browse your library, check for missing episodes, look up new series, and
trigger downloads via Sonarr's REST API.

Configuration is via environment variables:
  SONARR_URL      e.g. http://192.168.1.50:8989 (required)
  SONARR_API_KEY  Sonarr > Settings > General > API Key (required)
  MCP_HOST        interface to bind to (default 0.0.0.0)
  MCP_PORT        port to listen on (default 8931)
  MCP_AUTH_TOKEN  shared secret required as `Authorization: Bearer <token>`
                  on every request (optional — if unset, the server is open
                  to anyone who can reach it; see README for why that's a
                  real trade-off, not just a default to ignore)

Transport: streamable-http. This runs as a standing network service (bind
0.0.0.0 inside the container; publish the port only on your internal
network/VLAN — never forward it externally) rather than being spawned
per-client over stdio, so any MCP client on the LAN can connect to
http://<host>:<port>/mcp.

Auth here is a single shared bearer token checked by plain middleware, not
the SDK's built-in OAuth support (mcp.server.auth) — that machinery expects
a full OAuth authorization server (issuer/resource metadata, RFC 8414/8707/
9068 discovery), which is unwarranted complexity for a single internal
secret shared by trusted LAN clients.
"""

import hmac
import os
import sys

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: required environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


SONARR_URL = _require_env("SONARR_URL").rstrip("/")
SONARR_API_KEY = _require_env("SONARR_API_KEY")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8931"))
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")

client = httpx.Client(
    base_url=f"{SONARR_URL}/api/v3",
    headers={"X-Api-Key": SONARR_API_KEY},
    timeout=30,
)

mcp = MCPServer("sonarr")


@mcp.tool()
def list_series(title: str | None = None) -> list[dict]:
    """List TV series already in the Sonarr library, optionally filtered by a title substring."""
    response = client.get("/series")
    response.raise_for_status()
    series = response.json()

    if title:
        needle = title.lower()
        series = [s for s in series if needle in s["title"].lower()]

    return [
        {
            "id": s["id"],
            "title": s["title"],
            "year": s.get("year"),
            "monitored": s.get("monitored"),
            "status": s.get("status"),
            "network": s.get("network"),
            "percentOfEpisodes": s.get("statistics", {}).get("percentOfEpisodes"),
        }
        for s in series
    ]


@mcp.tool()
def series_details(series_id: int) -> dict:
    """Get full details for a single series by its Sonarr ID."""
    response = client.get(f"/series/{series_id}")
    response.raise_for_status()
    return response.json()


@mcp.tool()
def missing_episodes(series_id: int | None = None) -> list[dict]:
    """List missing/wanted episodes, optionally scoped to a single series ID."""
    params = {"pageSize": 200, "includeSeries": True}
    if series_id is not None:
        params["seriesId"] = series_id

    response = client.get("/wanted/missing", params=params)
    response.raise_for_status()
    return response.json()["records"]


@mcp.tool()
def lookup_series(term: str) -> list[dict]:
    """Search for new series to potentially add to Sonarr, by title. Does not add anything."""
    response = client.get("/series/lookup", params={"term": term})
    response.raise_for_status()
    return [
        {
            "title": s["title"],
            "year": s.get("year"),
            "tvdbId": s.get("tvdbId"),
            "overview": (s.get("overview") or "")[:300],
            "network": s.get("network"),
        }
        for s in response.json()
    ]


@mcp.tool()
def search_series(series_id: int) -> str:
    """Trigger Sonarr to search for missing episodes of a series that is already in the library."""
    response = client.post("/command", json={"name": "SeriesSearch", "seriesId": series_id})
    response.raise_for_status()
    return f"Search triggered for series {series_id}"


@mcp.tool()
def system_status() -> dict:
    """Get Sonarr system status, disk space, and health checks."""
    status, disk_space, health = (
        client.get("/system/status").json(),
        client.get("/diskspace").json(),
        client.get("/health").json(),
    )
    return {"status": status, "diskSpace": disk_space, "health": health}


# Paths that must stay reachable without MCP_AUTH_TOKEN, so Docker's own
# HEALTHCHECK, Dockhand's health probe, etc. don't need the secret.
UNAUTHENTICATED_PATHS = {"/health", "/ready"}


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Liveness check: the process is up and serving HTTP. Does not call Sonarr."""
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/ready", methods=["GET"])
async def ready(request: Request) -> Response:
    """Readiness check: SONARR_URL is reachable and SONARR_API_KEY is valid."""
    try:
        response = client.get("/system/status", timeout=5)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        reason = "invalid Sonarr API key" if status_code == 401 else f"Sonarr returned HTTP {status_code}"
        return JSONResponse(
            {"status": "error", "reachable": True, "authenticated": status_code != 401, "error": reason},
            status_code=503,
        )
    except httpx.RequestError as error:
        return JSONResponse(
            {
                "status": "error",
                "reachable": False,
                "authenticated": False,
                "error": f"cannot reach Sonarr at {SONARR_URL}: {error}",
            },
            status_code=503,
        )

    return JSONResponse(
        {
            "status": "ok",
            "reachable": True,
            "authenticated": True,
            "sonarr": {"url": SONARR_URL, "version": response.json().get("version")},
        }
    )


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <MCP_AUTH_TOKEN>` on every request except
    the health/readiness endpoints, which are meant to be publicly pollable."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, MCP_AUTH_TOKEN):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


if __name__ == "__main__":
    app = mcp.streamable_http_app(host=MCP_HOST)

    if MCP_AUTH_TOKEN:
        app.add_middleware(BearerTokenMiddleware)
        print("Auth enabled: Authorization: Bearer <token> required", file=sys.stderr)
    else:
        print("WARNING: MCP_AUTH_TOKEN not set — server is open to anyone who can reach it", file=sys.stderr)

    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)
