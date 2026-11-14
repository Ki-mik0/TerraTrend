"""City versus surroundings (PLAN_ANALYTICS section 8.7)."""

from __future__ import annotations

import numpy as np
import pytest

from earthtrend.analytics.simulate.synthetic import default_meta, generate_grid
from earthtrend.analytics.spatial.urban import (
    distance_to_mask_km,
    urban_contrast,
    urban_ring_mask,
)

# ~0.05 deg grid (~5.5 km) around 48.5N 35E, 21 x 21 cells.
LAT = 48.5 + 0.05 * (np.arange(21) - 10)
LON = 35.0 + 0.05 * (np.arange(21) - 10)


def city_mask() -> np.ndarray:
    m = np.zeros((21, 21), bool)
    m[9:12, 9:12] = True
    return m


def test_distance_to_mask() -> None:
    d = distance_to_mask_km(LAT, LON, city_mask())
    assert d[10, 10] == 0.0
    # 2 cells north of the city edge: 0.1 deg of latitude ~ 11.1 km
    assert d[13, 10] == pytest.approx(11.12, abs=0.05)


def test_ring_excludes_water_urban_and_relief() -> None:
    city = city_mask()
    base = urban_ring_mask(LAT, LON, city)
    assert base.any() and not (base & city).any()
    d = distance_to_mask_km(LAT, LON, city)
    assert d[base].min() >= 10 and d[base].max() <= 30
    water = np.zeros_like(city)
    water[:, :5] = True
    other_town = np.zeros_like(city)
    other_town[15:17, 15:17] = True
    elev = np.full(city.shape, 100.0)
    elev[:4, :] = 500.0  # hills in the south
    ring = urban_ring_mask(
        LAT, LON, city, urban_mask=other_town, water_mask=water, elevation_m=elev
    )
    assert not (ring & water).any()
    assert not (ring & other_town).any()
    assert not ring[:4].any()
    assert ring.sum() < base.sum()


def test_urban_heating_detected() -> None:
    city = city_mask()
    slope = np.full(city.shape, 0.2)
    slope[city] = 0.8  # city warms 0.6 K/decade faster
    dates, cube = generate_grid(slope_field=slope, phi=0.3, sigma=0.5, seed=1)
    # Shared regional weather: identical noise everywhere cancels in the difference.
    common = np.random.default_rng(2).normal(0, 1.0, len(dates))
    cube = cube + common[:, None, None]
    res = urban_contrast(cube, LAT, LON, dates, city, default_meta(region_id="dnipro"))
    assert res.ring is not None and res.difference is not None
    assert res.difference.verdict.code == "strong"
    assert res.difference.primary_slope_per_decade == pytest.approx(0.6, abs=0.15)
    assert "urban_heating" in res.patterns
    assert res.ring_n_cells >= 3 and res.ring_area_km2 > 0
    assert res.difference.meta.variable_id.endswith("__city_minus_ring")


def test_no_urban_effect_no_pattern() -> None:
    city = city_mask()
    dates, cube = generate_grid(slope_field=np.full(city.shape, 0.3), sigma=0.5, seed=3)
    res = urban_contrast(cube, LAT, LON, dates, city, default_meta(region_id="x"))
    assert res.patterns == []


def test_coarse_grid_ring_too_small() -> None:
    lat = 48.0 + 0.5 * np.arange(5)
    lon = 35.0 + 0.5 * np.arange(5)
    city = np.zeros((5, 5), bool)
    city[2, 2] = True
    dates, cube = generate_grid(slope_field=np.zeros((5, 5)), n_years=15, seed=4)
    res = urban_contrast(cube, lat, lon, dates, city, default_meta())
    assert "ring_too_small" in res.flags
    assert res.difference is None


def test_empty_city_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        urban_ring_mask(LAT, LON, np.zeros((21, 21), bool))
