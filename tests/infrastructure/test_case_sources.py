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


def _grid_series(root, variable_id: str = "omi_no2", first_year: int = 2005, years: int = 15) -> None:
    """A synthetic global cube: 2 inside the test box rising 0.1 per year, 100 everywhere else."""
    import json

    import numpy as np

    months = [f"{year}-{month:02d}" for year in range(first_year, first_year + years) for month in range(1, 13)]
    cube = np.full((len(months), 180, 360), 100.0, dtype=np.float32)
    lat = 89.5 - np.arange(180.0)
    lon = -179.5 + np.arange(360.0)
    rows = np.flatnonzero((lat >= 44) & (lat <= 52))
    cols = np.flatnonzero((lon >= 22) & (lon <= 40))
    for index, month in enumerate(months):
        cube[index][np.ix_(rows, cols)] = 2.0 + 0.1 * (int(month[:4]) - first_year)
    cube[0, rows[0], cols[0]] = np.nan  # a missing cell is skipped, not counted as zero
    root.mkdir(parents=True, exist_ok=True)
    np.save(root / f"{variable_id}.npy", cube)
    (root / f"{variable_id}.json").write_text(
        json.dumps({"dates": months, "units": "1e15 molec/cm2", "dataset": "NASA Earthdata OMI OMNO2d", "aggregation": "mean"}),
        encoding="utf-8",
    )


def test_grid_series_is_the_area_weighted_box_mean(tmp_path) -> None:
    from earthtrend.api.infrastructure.cases.sources import GRID_VERSION, GridSeriesSource

    _grid_series(tmp_path)
    grids = GridSeriesSource(tmp_path)
    assert grids.supports("omi_no2") and not grids.supports("modis_ndvi")
    series = grids.fetch(CaseSpec("omi_no2", "ukraine", "1990-01", "2030-12"), (22.0, 44.0, 40.0, 52.0), 600_000.0)
    assert series is not None
    assert series["meta"]["dataset_version"] == GRID_VERSION and series["meta"]["units"] == "1e15 molec/cm2"
    assert series["dates"][0] == "2005-01-01" and len(series["values"]) == 180  # clipped to the data years
    assert series["values"][0] == pytest.approx(2.0) and series["values"][-1] == pytest.approx(3.4)
    # a box smaller than a cell takes the nearest cell; a too short overlap gives nothing
    tiny = grids.fetch(CaseSpec("omi_no2", "kyiv", "2005-01", "2019-12"), (30.4, 50.3, 30.6, 50.5), 800.0)
    assert tiny is not None and tiny["values"][12] == pytest.approx(2.1)
    assert grids.fetch(CaseSpec("omi_no2", "kyiv", "2015-01", "2030-12"), (30.4, 50.3, 30.6, 50.5), None) is None


async def test_sourced_analysis_uses_the_grid_before_power_and_demo(tmp_path) -> None:
    from earthtrend.api.infrastructure.cases.sources import GRID_VERSION, GridSeriesSource

    _grid_series(tmp_path)
    analysis = SourcedAnalysis(MemoryAnalysis(), seed_catalog(), power=sources._OfflinePower(), grids=GridSeriesSource(tmp_path))
    product = await analysis.run(CaseSpec("omi_no2", "ukraine", "2005-01", "2019-12"))
    assert product.datasets_version == GRID_VERSION and product.verdict.direction == "increasing"
    series = await analysis.series_for(CaseSpec("omi_no2", "ukraine", "2005-01", "2019-12"))
    assert series is not None and series["meta"]["dataset_id"] == "NASA Earthdata OMI OMNO2d"
    demo = await analysis.run(CaseSpec("modis_ndvi", "sahel", "2000-01", "2019-12"))
    assert demo.datasets_version == DEMO_VERSION
