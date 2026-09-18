"""
Sonarr MCP Server

Exposes a small set of Sonarr (TV library manager) operations as MCP tools,
so an MCP-compatible AI assistant (e.g. Claude Code / Claude Desktop) can
browse your library, check for missing episodes, look up new series, and
trigger downloads via Sonarr's REST API.

Configuration is via environment variables:
  SONARR_URL      e.g. http://192.168.1.50:8989 (required)
  SONARR_API_KEY  Sonarr > Settings > General > API Key (required)

Transport: stdio (the standard MCP transport for locally-spawned servers).
"""

import os
import sys

import httpx
from mcp.server.mcpserver import MCPServer


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: required environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


SONARR_URL = _require_env("SONARR_URL").rstrip("/")
SONARR_API_KEY = _require_env("SONARR_API_KEY")

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


if __name__ == "__main__":
    mcp.run()
