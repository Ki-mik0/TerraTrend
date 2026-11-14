"""City versus its surroundings (docs/PLAN_ANALYTICS.md section 8.7).

The ring is the set of cells 10-30 km from the city that are neither built-up nor water and
lie within 200 m of the city's median elevation, so the comparison isolates the urban
effect from relief and coast. The city series, the ring series and their difference
``city - ring`` each get the full analysis; a significant positive trend of the difference
is the ``urban_heating`` pattern (section 10.3) for temperature-like variables.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.models import AnalysisOptions, RegionalSeries, SeriesMeta, TrendResult
from earthtrend.analytics.regional.reduce import regional_series
from earthtrend.analytics.spatial.zones import cell_area_km2

RING_INNER_KM = 10.0
RING_OUTER_KM = 30.0
RING_MAX_DZ_M = 200.0
RING_MIN_CELLS = 3


class UrbanContrast(BaseModel):
    city: TrendResult
    ring: TrendResult | None
    difference: TrendResult | None  # city - ring
    city_n_cells: int
    ring_n_cells: int
    ring_area_km2: float
    patterns: list[str]
    flags: list[str]  # ring_too_small, ring_from_caller


def _haversine_km(
    lat1: NDArray[np.float64], lon1: NDArray[np.float64], lat2: float, lon2: float
) -> NDArray[np.float64]:
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dphi = p2 - p1
    dl = np.deg2rad(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return np.asarray(2 * config.EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1))))


def distance_to_mask_km(
    lat: NDArray[np.float64], lon: NDArray[np.float64], mask: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Great-circle distance from every cell centre to the nearest centre of a ``mask`` cell."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    glat, glon = np.meshgrid(lat, lon, indexing="ij")
    out = np.full(mask.shape, np.inf)
    for i, j in zip(*np.nonzero(mask), strict=True):
        np.minimum(out, _haversine_km(glat, glon, float(lat[i]), float(lon[j])), out=out)
    return out


def urban_ring_mask(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    city_mask: NDArray[np.bool_],
    *,
    urban_mask: NDArray[np.bool_] | None = None,
    water_mask: NDArray[np.bool_] | None = None,
    elevation_m: NDArray[np.float64] | None = None,
    inner_km: float = RING_INNER_KM,
    outer_km: float = RING_OUTER_KM,
    max_dz_m: float = RING_MAX_DZ_M,
) -> NDArray[np.bool_]:
    """Ring cells: ``inner_km <= distance to city <= outer_km``, not built-up (``urban_mask``,
    default the city itself), not water, and ``|elevation - city median| < max_dz_m``."""
    city = np.asarray(city_mask, dtype=bool)
    if not city.any():
        raise ValueError("city mask is empty")
    d = distance_to_mask_km(lat, lon, city)
    ring = (d >= inner_km) & (d <= outer_km) & ~city
    if urban_mask is not None:
        ring &= ~np.asarray(urban_mask, dtype=bool)
    if water_mask is not None:
        ring &= ~np.asarray(water_mask, dtype=bool)
    if elevation_m is not None:
        elev = np.asarray(elevation_m, dtype=np.float64)
        z_city = float(np.nanmedian(elev[city]))
        with np.errstate(invalid="ignore"):
            ring &= np.abs(elev - z_city) < max_dz_m
    return np.asarray(ring)


def difference_series(a: RegionalSeries, b: RegionalSeries, meta: SeriesMeta) -> RegionalSeries:
    """``a - b`` on common dates; a gap in either is a gap."""
    vb = dict(zip(b.dates, b.values, strict=True))
    dates: list[date] = []
    values: list[float | None] = []
    for d, v in zip(a.dates, a.values, strict=True):
        if d not in vb:
            continue
        w = vb[d]
        dates.append(d)
        values.append(None if v is None or w is None else v - w)
    return RegionalSeries(
        meta=meta,
        dates=dates,
        values=values,
        stable_fraction=min(a.stable_fraction, b.stable_fraction),
    )


def urban_contrast(
    cube: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    dates: Sequence[date],
    city_mask: NDArray[np.bool_],
    meta: SeriesMeta,
    options: AnalysisOptions | None = None,
    *,
    ring_mask: NDArray[np.bool_] | None = None,
    urban_mask: NDArray[np.bool_] | None = None,
    water_mask: NDArray[np.bool_] | None = None,
    elevation_m: NDArray[np.float64] | None = None,
    heating_variable: bool = True,
) -> UrbanContrast:
    """Monthly cube (time, lat, lon) -> city, ring and difference analyses.

    ``meta.region_id`` names the city. Pass ``ring_mask`` to override the automatic ring.
    ``heating_variable`` enables the ``urban_heating`` pattern (temperature, LST).
    The ring needs a grid finer than its width (~20 km): at 0.25 deg it is usually empty and
    the result carries ``ring_too_small``.
    """
    city = np.asarray(city_mask, dtype=bool)
    flags: list[str] = []
    if ring_mask is None:
        ring = urban_ring_mask(
            lat, lon, city, urban_mask=urban_mask, water_mask=water_mask, elevation_m=elevation_m
        )
    else:
        ring = np.asarray(ring_mask, dtype=bool) & ~city
        flags.append("ring_from_caller")

    city_s = regional_series(cube, lat, lon, city, dates, meta)
    city_r = analyze_series(city_s, options)
    areas = cell_area_km2(np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64))
    n_ring = int(ring.sum())
    if n_ring < RING_MIN_CELLS:
        flags.append("ring_too_small")
        return UrbanContrast(
            city=city_r,
            ring=None,
            difference=None,
            city_n_cells=int(city.sum()),
            ring_n_cells=n_ring,
            ring_area_km2=float(areas[ring].sum()),
            patterns=[],
            flags=flags,
        )

    ring_meta = meta.model_copy(update={"region_id": f"{meta.region_id}__ring"})
    ring_s = regional_series(cube, lat, lon, ring, dates, ring_meta)
    ring_r = analyze_series(ring_s, options)
    diff_meta = meta.model_copy(
        update={
            "region_id": f"{meta.region_id}__minus_ring",
            "variable_id": f"{meta.variable_id}__city_minus_ring",
            "transform": "none",
            "ratio_scale": False,
        }
    )
    diff_r = analyze_series(difference_series(city_s, ring_s, diff_meta), options)

    patterns: list[str] = []
    if (
        heating_variable
        and diff_r.verdict.code in {"proven", "strong"}
        and diff_r.verdict.direction == "increasing"
    ):
        patterns.append("urban_heating")
    return UrbanContrast(
        city=city_r,
        ring=ring_r,
        difference=diff_r,
        city_n_cells=int(city.sum()),
        ring_n_cells=n_ring,
        ring_area_km2=float(areas[ring].sum()),
        patterns=patterns,
        flags=flags,
    )
