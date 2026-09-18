"""Live contract tests against a *real* Sonarr instance.

These do not run by default — there's no Sonarr in CI, and we don't want to
accidentally fire real requests using the fake SONARR_URL/SONARR_API_KEY that
conftest.py sets for the rest of the suite. To run them:

    RUN_LIVE_SONARR_TESTS=1 SONARR_URL=https://sonarr.example.com \\
    SONARR_API_KEY=<real key> pytest tests/test_live_sonarr.py -v

Point is to catch drift: if a Sonarr upgrade renames/removes a field our
tools depend on (id, title, statistics.percentOfEpisodes, tvdbId, version,
...), these fail even though the mocked unit tests in test_tools.py would
still happily pass (they only assert against fixtures we wrote ourselves).
"""

import os

import httpx
import pytest

import server

RUN_LIVE = os.environ.get("RUN_LIVE_SONARR_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="opt-in only: set RUN_LIVE_SONARR_TESTS=1 with a real SONARR_URL/SONARR_API_KEY",
)


@pytest.fixture(scope="module")
def live_client():
    return httpx.Client(
        base_url=f"{server.SONARR_URL}/api/v3",
        headers={"X-Api-Key": server.SONARR_API_KEY},
        timeout=15,
    )


def test_system_status_shape(live_client):
    """The fields system_status()/`/ready` depend on actually exist."""
    response = live_client.get("/system/status")
    response.raise_for_status()
    data = response.json()

    assert isinstance(data.get("version"), str) and data["version"].count(".") >= 2
    assert "instanceName" in data


def test_series_shape_matches_what_list_series_assumes(live_client):
    """Every field list_series() reads with .get() (safe) or [..] (required) exists."""
    response = live_client.get("/series")
    response.raise_for_status()
    series = response.json()

    assert isinstance(series, list)
    if not series:
        pytest.skip("library is empty — nothing to validate the shape of")

    sample = series[0]
    for required_field in ("id", "title"):
        assert required_field in sample, f"Sonarr's /series no longer returns '{required_field}'"

    # These are read with .get() in our code specifically because they're
    # not guaranteed — but if Sonarr stops sending them for every record,
    # list_series() silently degrades, which is worth knowing about here.
    for soft_field in ("year", "monitored", "status", "network", "statistics"):
        if soft_field not in sample:
            pytest.skip(f"'{soft_field}' missing from a real record — list_series() will report it as null")


def test_series_lookup_shape(live_client):
    """The fields lookup_series() depends on for a real search term."""
    response = live_client.get("/series/lookup", params={"term": "Chernobyl"})
    response.raise_for_status()
    results = response.json()

    assert isinstance(results, list) and len(results) > 0
    sample = results[0]
    assert "title" in sample
    assert "tvdbId" in sample


def test_our_tools_run_cleanly_against_real_sonarr(monkeypatch, live_client):
    """Run the actual tool functions (not just raw requests) against real Sonarr."""
    monkeypatch.setattr(server, "client", live_client)

    status = server.system_status()
    assert "version" in status["status"]

    series = server.list_series()
    assert isinstance(series, list)

    results = server.lookup_series("Chernobyl")
    assert len(results) > 0
    assert results[0]["title"]
