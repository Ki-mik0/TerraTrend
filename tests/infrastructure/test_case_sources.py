import asyncio

import httpx
import pytest
from litestar.testing import TestClient

from earthtrend.api.domain.cases.model import CaseError, CaseSpec
from earthtrend.api.infrastructure.cases import sources
from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis
from earthtrend.api.infrastructure.cases.sources import (
    DEMO_VERSION,
    POWER_VERSION,
    DemoSeriesSource,
    PowerSeriesSource,
    SourcedAnalysis,
    sourced_analysis_from_env,
)
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.shared.cache import MemoryCache
from earthtrend.api.main import create_app

SPEC = CaseSpec("merra2_t2m", "ukraine_north", "2000-01", "2019-12")


def _power_transport(calls: list[httpx.Request], *, broken: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if broken:
            return httpx.Response(503)
        start, end = int(request.url.params["start"]), int(request.url.params["end"])
        values = {}
        for year in range(start, end + 1):
            for month in range(1, 13):
                values[f"{year}{month:02d}"] = 5 + 10 * (month in (6, 7, 8)) + 0.05 * (year - start)
            values[f"{year}13"] = 9.9  # the annual mean row is skipped
        values[f"{start}01"] = -999.0  # a gap
        return httpx.Response(200, json={"properties": {"parameter": {request.url.params["parameters"]: values}}})

    return httpx.MockTransport(handler)


async def test_power_series_averages_points_and_is_cached() -> None:
    calls: list[httpx.Request] = []
    cache = MemoryCache()
    async with httpx.AsyncClient(transport=_power_transport(calls)) as client:
        power = PowerSeriesSource(cache, client)
        series = await power.fetch(SPEC, (24.0, 50.0, 36.0, 52.5), 90_000.0)
        again = await power.fetch(SPEC, (24.0, 50.0, 36.0, 52.5), 90_000.0)
    assert series == again and len(calls) == 5  # five points once, then the cache
    assert series["meta"]["dataset_version"] == POWER_VERSION and series["meta"]["units"] == "°C"
    assert len(series["dates"]) == 240 and series["dates"][0] == "2000-01-01"
    assert series["values"][0] is None and series["values"][6] == pytest.approx(15.0)
    assert {call.url.params["parameters"] for call in calls} == {"T2M"}
    assert await power.fetch(CaseSpec("modis_ndvi", "sahel", "2000-01", "2019-12"), (0, 0, 1, 1), None) is None


async def test_power_outage_returns_nothing() -> None:
    async with httpx.AsyncClient(transport=_power_transport([], broken=True)) as client:
        assert await PowerSeriesSource(None, client).fetch(SPEC, (24.0, 50.0, 36.0, 52.5), None) is None


def test_demo_series_is_deterministic_and_checks_the_period() -> None:
    demo = DemoSeriesSource()
    first = demo.fetch(CaseSpec("modis_ndvi", "sahel", "2001-01", "2020-12"), "1", None)
    assert first == demo.fetch(CaseSpec("modis_ndvi", "sahel", "2001-01", "2020-12"), "1", None)
    assert first["meta"]["dataset_version"] == DEMO_VERSION and len(first["values"]) == 240
    with pytest.raises(CaseError):
        demo.fetch(CaseSpec("modis_ndvi", "sahel", "2015-01", "2020-12"), "1", None)


async def test_sourced_analysis_prefers_power_then_curated_then_demo() -> None:
    catalog = seed_catalog()
    calls: list[httpx.Request] = []
    offline = SourcedAnalysis(MemoryAnalysis(), catalog, power=sources._OfflinePower())
    curated = await offline.run(CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2024-12"))
    assert curated.datasets_version not in {POWER_VERSION, DEMO_VERSION}  # POWER silent: the curated product
    async with httpx.AsyncClient(transport=_power_transport(calls)) as client:
        analysis = SourcedAnalysis(MemoryAnalysis(), catalog, power=PowerSeriesSource(None, client))
        real = await analysis.run(CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2024-12"))
        assert real.datasets_version == POWER_VERSION and calls  # real data wins over the curated summary
        powered = await analysis.run(SPEC)
        assert powered.datasets_version == POWER_VERSION and powered.result_hash
        assert powered.verdict.direction == "increasing"
        demo = await analysis.run(CaseSpec("modis_ndvi", "sahel", "2000-01", "2019-12"))
        assert demo.datasets_version == DEMO_VERSION
    with pytest.raises(CaseError):
        await analysis.run(CaseSpec("made_up", "sahel", "2000-01", "2019-12"))


def test_offline_switch(monkeypatch) -> None:
    monkeypatch.setenv("NASA_POWER", "off")
    analysis = sourced_analysis_from_env(seed_catalog())
    result = asyncio.run(analysis.run(SPEC))
    assert result.datasets_version == DEMO_VERSION
    monkeypatch.setenv("NASA_POWER", "on")
    assert type(sourced_analysis_from_env(seed_catalog())._power) is sources.PowerSeriesSource


def test_compare_and_cases_work_for_any_catalog_pair() -> None:
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        compared = client.post(
            "/api/v1/cases/compare",
            json={"variable_id": "merra2_t2m", "region_ids": ["ukraine_south", "ukraine_north"], "period_start": "2000-01", "period_end": "2024-12"},
            headers=headers,
        )
        assert compared.status_code == 201, compared.text
        cases = compared.json()["cases"]
        assert [item["status"] for item in cases] == ["completed", "completed"]
        assert cases[1]["datasets_version"] == DEMO_VERSION  # NASA_POWER is off in tests
        evidence = client.get(f"/api/v1/cases/{cases[1]['id']}/evidence", headers=headers)
        assert evidence.status_code == 200


def test_case_response_carries_slope_and_direction() -> None:
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        created = client.post(
            "/api/v1/cases",
            json={"variable_id": "gldas_sm", "region_id": "ukraine_south", "period_start": "2000-01", "period_end": "2024-12"},
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert isinstance(created["slope_decade"], float) and created["direction"] in {"increasing", "decreasing", "none"}
