"""Monthly regional series for variable × region pairs that have no curated analysis product.

- NASA Earthdata grids: real monthly 1 degree cubes that `scripts/earthdata_grids.py` saves under
  `STORAGE_ROOT/grids/series/`. A region is the area-weighted mean of the cells inside its bounding box.
- NASA POWER: real monthly values (free API, no key) for temperature, precipitation and soil wetness.
  A region is the mean of five points spread over its bounding box. Responses are cached.
- Demo: a deterministic synthetic series for every other variable, so the product still works.
  Such a case carries `datasets_version = "demo-synthetic-v1"` and the UI labels it as demo data.

The series then goes through the same analytics as an uploaded series (`product_from_series`).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import zlib
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import structlog

from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.domain.cases.codec import seal
from earthtrend.api.domain.cases.model import AnalysisProduct, CaseError, CaseSpec

_log = structlog.get_logger("cases.sources")

POWER_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
POWER_FIRST_YEAR = 1981
POWER_TTL = 30 * 24 * 3600
POWER_VERSION = "nasa-power-v1"
DEMO_VERSION = "demo-synthetic-v1"
GRID_VERSION = "earthdata-grid-v1"

# catalog variable -> (POWER parameter, units, aggregation)
POWER_PARAMETERS: dict[str, tuple[str, str, str]] = {
    "merra2_t2m": ("T2M", "°C", "mean"),
    "airs_t": ("T2M", "°C", "mean"),
    "modis_lst": ("TS", "°C", "mean"),
    "gldas_sm": ("GWETROOT", "1", "mean"),
    "merra2_sfmc": ("GWETTOP", "1", "mean"),
    "merra2_prectot": ("PRECTOTCORR", "mm/day", "mean"),
    "gpm_imerg": ("PRECTOTCORR", "mm/day", "mean"),
}


def _years(spec: CaseSpec) -> tuple[int, int]:
    start = max(int(spec.period_start[:4]), POWER_FIRST_YEAR)
    end = min(int(spec.period_end[:4]), date.today().year - 1)
    if end - start < 9:
        raise CaseError("period_too_short", "Для тренду потрібно щонайменше 10 років даних")
    return start, end


def _points(bbox: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """Centre plus four inner points of the bounding box, as (lon, lat)."""
    west, south, east, north = bbox
    lons = (west + (east - west) * 0.25, west + (east - west) * 0.5, west + (east - west) * 0.75)
    lats = (south + (north - south) * 0.25, south + (north - south) * 0.5, south + (north - south) * 0.75)
    chosen = [(lons[1], lats[1]), (lons[0], lats[0]), (lons[2], lats[0]), (lons[0], lats[2]), (lons[2], lats[2])]
    return [(round(lon, 2), round(max(-89.5, min(89.5, lat)), 2)) for lon, lat in chosen]


def _meta(spec: CaseSpec, *, dataset_id: str, version: str, units: str, aggregation: str, area: float | None) -> dict[str, Any]:
    return {
        "variable_id": spec.variable_id,
        "concept_id": spec.variable_id,
        "dataset_id": dataset_id,
        "dataset_version": version,
        "units": units,
        "region_id": spec.region_id,
        "region_area_km2": area,
        "frequency": "monthly",
        "aggregation": aggregation,
    }


class PowerSeriesSource:
    def __init__(self, cache: CachePort | None = None, client: httpx.AsyncClient | None = None, timeout: float = 25.0) -> None:
        self._cache = cache
        self._client = client
        self._timeout = timeout

    def supports(self, variable_id: str) -> bool:
        return variable_id in POWER_PARAMETERS

    async def fetch(self, spec: CaseSpec, bbox: tuple[float, float, float, float], area: float | None) -> dict[str, Any] | None:
        if not self.supports(spec.variable_id):
            return None
        parameter, units, aggregation = POWER_PARAMETERS[spec.variable_id]
        start, end = _years(spec)
        points = _points(bbox)
        key = f"case:power:{parameter}:{':'.join(f'{lon},{lat}' for lon, lat in points)}:{start}:{end}"
        rows = await self._cache.get_json(key) if self._cache is not None else None
        if rows is None:
            try:
                rows = await self._download(parameter, points, start, end)
            except (httpx.HTTPError, ValueError, KeyError) as error:
                _log.warning("power_unavailable", parameter=parameter, reason=str(error))
                return None
            if self._cache is not None:
                await self._cache.set_json(key, rows, POWER_TTL)
        dates, values = self._average(rows, start, end)
        if sum(value is not None for value in values) < 12 * 10:
            return None
        return {
            "meta": _meta(spec, dataset_id=f"NASA POWER {parameter}", version=POWER_VERSION, units=units, aggregation=aggregation, area=area),
            "dates": dates,
            "values": values,
        }

    async def _download(self, parameter: str, points: list[tuple[float, float]], start: int, end: int) -> list[dict[str, float]]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            responses = await asyncio.gather(
                *(
                    client.get(
                        POWER_URL,
                        params={
                            "parameters": parameter,
                            "community": "AG",
                            "longitude": lon,
                            "latitude": lat,
                            "start": start,
                            "end": end,
                            "format": "JSON",
                        },
                    )
                    for lon, lat in points
                )
            )
        finally:
            if self._client is None:
                await client.aclose()
        rows = []
        for response in responses:
            response.raise_for_status()
            rows.append(response.json()["properties"]["parameter"][parameter])
        return rows

    @staticmethod
    def _average(rows: list[dict[str, float]], start: int, end: int) -> tuple[list[str], list[float | None]]:
        dates: list[str] = []
        values: list[float | None] = []
        for year in range(start, end + 1):
            for month in range(1, 13):
                key = f"{year}{month:02d}"
                found = [row[key] for row in rows if key in row and row[key] is not None and row[key] > -900]
                dates.append(f"{year}-{month:02d}-01")
                values.append(round(sum(found) / len(found), 4) if found else None)
        return dates, values


class GridSeriesSource:
    """Regional monthly series cut from the global 1 degree cubes of real NASA Earthdata collections."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(os.environ.get("STORAGE_ROOT", "data/storage")) / "grids" / "series"

    def supports(self, variable_id: str) -> bool:
        return (self._root / f"{variable_id}.json").is_file() and (self._root / f"{variable_id}.npy").is_file()

    def fetch(self, spec: CaseSpec, bbox: tuple[float, float, float, float], area: float | None) -> dict[str, Any] | None:
        if not self.supports(spec.variable_id):
            return None
        try:
            meta = json.loads((self._root / f"{spec.variable_id}.json").read_text(encoding="utf-8"))
            cube = np.load(self._root / f"{spec.variable_id}.npy", mmap_mode="r")
        except (OSError, ValueError) as error:
            _log.warning("grid_series_unreadable", variable_id=spec.variable_id, reason=str(error))
            return None
        months: list[str] = meta["dates"]
        if cube.shape != (len(months), 180, 360):
            return None
        start = max(int(spec.period_start[:4]), int(months[0][:4]))
        end = min(int(spec.period_end[:4]), int(months[-1][:4]))
        if end - start < 9:
            return None
        rows, cols, weights = _cells(bbox)
        keep = [index for index, month in enumerate(months) if start <= int(month[:4]) <= end]
        block = np.asarray(cube[keep[0] : keep[-1] + 1][:, rows][:, :, cols], dtype=np.float64)
        finite = np.isfinite(block)
        weight = np.where(finite, weights[None, :, None], 0.0)
        total = weight.sum(axis=(1, 2))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(total > 0, (np.where(finite, block, 0.0) * weight).sum(axis=(1, 2)) / total, np.nan)
        values = [round(float(value), 6) if np.isfinite(value) else None for value in mean]
        if sum(value is not None for value in values) < 12 * 10:
            return None
        return {
            "meta": _meta(
                spec,
                dataset_id=str(meta.get("dataset", spec.variable_id)),
                version=GRID_VERSION,
                units=str(meta.get("units", "1")),
                aggregation=str(meta.get("aggregation", "mean")),
                area=area,
            ),
            "dates": [f"{months[index]}-01" for index in keep],
            "values": values,
        }


def _cells(bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rows and columns of the 1 degree cells whose centres fall inside the box (the nearest cell if none)."""
    west, south, east, north = bbox
    lat = 89.5 - np.arange(180.0)
    lon = -179.5 + np.arange(360.0)
    rows = np.flatnonzero((lat >= south) & (lat <= north))
    if not rows.size:
        rows = np.array([int(np.argmin(np.abs(lat - (south + north) / 2)))])
    inside = (lon >= west) & (lon <= east) if west <= east else (lon >= west) | (lon <= east)
    cols = np.flatnonzero(inside)
    if not cols.size:
        centre = (west + east) / 2 if west <= east else ((west + east + 360) / 2 + 180) % 360 - 180
        cols = np.array([int(np.argmin(np.abs((lon - centre + 180) % 360 - 180)))])
    return rows, cols, np.cos(np.radians(lat[rows]))


class DemoSeriesSource:
    """A reproducible synthetic monthly series: seasonal cycle, a trend and red noise."""

    def fetch(self, spec: CaseSpec, units: str, area: float | None) -> dict[str, Any]:
        start = int(spec.period_start[:4])
        end = int(spec.period_end[:4])
        if end - start < 9:
            raise CaseError("period_too_short", "Для тренду потрібно щонайменше 10 років даних")
        rng = np.random.default_rng(zlib.crc32(f"{spec.variable_id}|{spec.region_id}".encode()))
        months = (end - start + 1) * 12
        slope_per_decade = float(rng.uniform(-0.8, 0.8))
        noise = np.zeros(months)
        for index in range(1, months):
            noise[index] = 0.5 * noise[index - 1] + rng.normal(0, 0.6)
        values = [
            round(10 + 3 * math.sin(2 * math.pi * (index % 12) / 12) + slope_per_decade * index / 120 + float(noise[index]), 4)
            for index in range(months)
        ]
        dates = [f"{start + index // 12}-{index % 12 + 1:02d}-01" for index in range(months)]
        return {
            "meta": _meta(spec, dataset_id="demo synthetic series", version=DEMO_VERSION, units=units or "1", aggregation="mean", area=area),
            "dates": dates,
            "values": values,
        }


class SourcedAnalysis:
    """Real data first (the Earthdata grid of that very collection, else NASA POWER); a curated product
    when neither has the variable; otherwise a demo series.

    The curated products are precomputed summaries kept for offline runs, so wherever real data has the
    variable the case is built from the real monthly series instead.
    """

    def __init__(
        self,
        curated: Any,
        catalog: Any,
        power: PowerSeriesSource | None = None,
        demo: DemoSeriesSource | None = None,
        grids: GridSeriesSource | None = None,
    ) -> None:
        self._curated = curated
        self._catalog = catalog
        self._power = power or PowerSeriesSource()
        self._demo = demo or DemoSeriesSource()
        self._grids = grids
        self.catalog_version = curated.catalog_version
        self.datasets_version = f"{curated.datasets_version}+sourced"
        self.algorithm_version = curated.algorithm_version

    async def run(self, spec: CaseSpec) -> AnalysisProduct:
        series = await self._power_series(spec)
        version = series["meta"]["dataset_version"] if series is not None else POWER_VERSION
        if series is None:
            try:
                return await self._curated.run(spec)
            except CaseError as error:
                if error.code != "data_not_ready":
                    raise
            series, version = await self._series(spec)
        from earthtrend.api.infrastructure.analytics_bridge import product_from_series, run_blocking

        try:
            product, _ = await run_blocking(product_from_series, series)
        except (ValueError, TypeError) as error:
            raise CaseError("data_not_ready", f"Аналітика не змогла обробити ряд: {error}") from error
        return seal(
            replace(
                product,
                catalog_version=self.catalog_version,
                datasets_version=version,
                algorithm_version=self.algorithm_version,
                result_hash="",
            )
        )

    async def series_for(self, spec: CaseSpec) -> dict[str, Any] | None:
        """The monthly series behind a sourced case, for charts, exports and Story Lens. None for curated products."""
        real = await self._power_series(spec)
        if real is not None:
            return real
        try:
            await self._curated.run(spec)
            return None
        except CaseError as error:
            if error.code != "data_not_ready":
                return None
        try:
            series, _ = await self._series(spec)
        except CaseError:
            return None
        return series

    async def _power_series(self, spec: CaseSpec) -> dict[str, Any] | None:
        """The real series: the Earthdata grid when it holds the variable, else NASA POWER."""
        on_grid = self._grids is not None and self._grids.supports(spec.variable_id)
        if not on_grid and not self._power.supports(spec.variable_id):
            return None
        region, _ = await self._lookup(spec)
        bbox, area = tuple(region.bbox), getattr(region, "area_km2", None)
        if on_grid and self._grids is not None:
            found = await asyncio.to_thread(self._grids.fetch, spec, bbox, area)
            if found is not None:
                return found
        return await self._power.fetch(spec, bbox, area)

    async def _lookup(self, spec: CaseSpec) -> tuple[Any, Any]:
        try:
            return await self._catalog.get_region(spec.region_id), await self._catalog.get_variable(spec.variable_id)
        except Exception as error:  # CatalogError: an unknown id is the caller's mistake, said in case terms
            raise CaseError(getattr(error, "code", "data_not_ready"), getattr(error, "message", str(error))) from error

    async def _series(self, spec: CaseSpec) -> tuple[dict[str, Any], str]:
        try:
            region = await self._catalog.get_region(spec.region_id)
            passport = await self._catalog.get_variable(spec.variable_id)
        except Exception as error:  # CatalogError: an unknown id is the caller's mistake, said in case terms
            raise CaseError(getattr(error, "code", "data_not_ready"), getattr(error, "message", str(error))) from error
        area = getattr(region, "area_km2", None)
        series = await self._power.fetch(spec, tuple(region.bbox), area)
        if series is not None:
            return series, POWER_VERSION
        return self._demo.fetch(spec, getattr(passport, "units", "1"), area), DEMO_VERSION


def sourced_analysis_from_env(catalog: Any, cache: CachePort | None = None) -> SourcedAnalysis:
    """`NASA_POWER=off` keeps cases offline (tests, air-gapped demos); demo series still fill the gaps."""
    from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis

    offline = os.environ.get("NASA_POWER", "on").lower() == "off"
    power = None if offline else PowerSeriesSource(cache)
    grids = None if offline else GridSeriesSource()
    return SourcedAnalysis(MemoryAnalysis(), catalog, power=power or _OfflinePower(), grids=grids)


class _OfflinePower(PowerSeriesSource):
    async def fetch(self, spec: CaseSpec, bbox: tuple[float, float, float, float], area: float | None) -> dict[str, Any] | None:
        del spec, bbox, area
        return None
