"""Unit tests for each MCP tool's logic, against a mocked Sonarr.

`@mcp.tool()` returns the original function unchanged, so these call the
tools directly as plain Python functions — no MCP protocol/session machinery
involved here (that's covered separately in test_http.py).
"""

import httpx
import pytest

import server

SAMPLE_SERIES = [
    {
        "id": 1,
        "title": "Chernobyl",
        "year": 2019,
        "monitored": True,
        "status": "ended",
        "network": "HBO",
        "statistics": {"percentOfEpisodes": 100.0},
    },
    {
        "id": 2,
        "title": "The Wire",
        "year": 2002,
        "monitored": True,
        "status": "ended",
        "network": "HBO",
        "statistics": {"percentOfEpisodes": 50.0},
    },
]


def test_list_series_returns_shaped_records(mock_sonarr):
    mock_sonarr(lambda req: httpx.Response(200, json=SAMPLE_SERIES))

    result = server.list_series()

    assert len(result) == 2
    assert result[0] == {
        "id": 1,
        "title": "Chernobyl",
        "year": 2019,
        "monitored": True,
        "status": "ended",
        "network": "HBO",
        "percentOfEpisodes": 100.0,
    }


def test_list_series_filters_by_title_case_insensitive(mock_sonarr):
    mock_sonarr(lambda req: httpx.Response(200, json=SAMPLE_SERIES))

    result = server.list_series(title="wire")

    assert len(result) == 1
    assert result[0]["title"] == "The Wire"


def test_list_series_missing_statistics_defaults_to_none(mock_sonarr):
    mock_sonarr(lambda req: httpx.Response(200, json=[{"id": 1, "title": "No Stats"}]))

    result = server.list_series()

    assert result[0]["percentOfEpisodes"] is None


def test_list_series_propagates_http_errors(mock_sonarr):
    mock_sonarr(lambda req: httpx.Response(500, json={"message": "boom"}))

    with pytest.raises(httpx.HTTPStatusError):
        server.list_series()


def test_series_details_hits_correct_path(mock_sonarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/series/42"
        return httpx.Response(200, json={"id": 42, "title": "Chernobyl"})

    mock_sonarr(handler)

    result = server.series_details(42)

    assert result == {"id": 42, "title": "Chernobyl"}


def test_missing_episodes_without_series_id(mock_sonarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "seriesId" not in request.url.params
        assert request.url.params["pageSize"] == "200"
        return httpx.Response(200, json={"records": [{"id": 1}]})

    mock_sonarr(handler)

    assert server.missing_episodes() == [{"id": 1}]


def test_missing_episodes_scoped_to_series(mock_sonarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["seriesId"] == "7"
        return httpx.Response(200, json={"records": []})

    mock_sonarr(handler)

    assert server.missing_episodes(series_id=7) == []


def test_lookup_series_shapes_and_truncates_overview(mock_sonarr):
    long_overview = "x" * 500

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/series/lookup"
        assert request.url.params["term"] == "chernobyl"
        return httpx.Response(
            200,
            json=[
                {
                    "title": "Chernobyl",
                    "year": 2019,
                    "tvdbId": 360893,
                    "overview": long_overview,
                    "network": "HBO",
                }
            ],
        )

    mock_sonarr(handler)

    result = server.lookup_series("chernobyl")

    assert result[0]["title"] == "Chernobyl"
    assert result[0]["tvdbId"] == 360893
    assert len(result[0]["overview"]) == 300


def test_lookup_series_handles_missing_overview(mock_sonarr):
    mock_sonarr(lambda req: httpx.Response(200, json=[{"title": "X", "overview": None}]))

    result = server.lookup_series("x")

    assert result[0]["overview"] == ""


def test_search_series_posts_correct_command(mock_sonarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/command"
        import json

        body = json.loads(request.content)
        assert body == {"name": "SeriesSearch", "seriesId": 99}
        return httpx.Response(201, json={"id": 123, "status": "queued"})

    mock_sonarr(handler)

    result = server.search_series(99)

    assert result == "Search triggered for series 99"


def test_system_status_combines_three_endpoints(mock_sonarr):
    def handler(request: httpx.Request) -> httpx.Response:
        payloads = {
            "/api/v3/system/status": {"version": "4.0.9"},
            "/api/v3/diskspace": [{"freeSpace": 123}],
            "/api/v3/health": [{"type": "warning"}],
        }
        return httpx.Response(200, json=payloads[request.url.path])

    mock_sonarr(handler)

    result = server.system_status()

    assert result["status"]["version"] == "4.0.9"
    assert result["diskSpace"] == [{"freeSpace": 123}]
    assert result["health"] == [{"type": "warning"}]
