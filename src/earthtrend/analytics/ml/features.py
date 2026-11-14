"""Feature matrix of M2 TrendPotential (docs/PLAN_ANALYTICS.md section 11.3).

One row per (region, variable, season). Region and variable descriptors only; trends of
the target variable are forbidden (``assert_no_leak``). Categorical fields are integer
codes from a vocabulary saved with the model; unseen values become NaN, which is what
the cold-start test (variables absent from training) exercises.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics.ml.potential_models import (
    LAND_COVER_CLASSES,
    ReasonCode,
    RegionFeatures,
    VariableInfo,
)

KOPPEN = ("A", "B", "C", "D", "E")
SEASONS = ("annual", "DJF", "MAM", "JJA", "SON")

NUMERIC = (
    "lat_sin",
    "lat_cos",
    "lon_sin",
    "lon_cos",
    "abs_lat",
    "log_area",
    "coast_share",
    "log_dist_to_sea",
    "elev_mean_m",
    "elev_range_m",
    *(f"lc_{c}" for c in LAND_COVER_CLASSES),
    "clim_t_c",
    "log_clim_pr",
    "clim_ndvi",
    "seasonal_amplitude_c",
    "aridity_index",
    "koppen_code",
    "log_pop_density",
    "pop_change_pct",
    "built_share",
    "record_years",
    "noise_level",
)
CATEGORICAL = ("variable_code", "concept_code", "domain_code", "season_code")
FEATURE_NAMES: tuple[str, ...] = NUMERIC + CATEGORICAL

# Substrings that would mean a feature carries the answer.
_LEAK_MARKERS = ("slope", "trend", "p_mk", "q_", "snr", "verdict", "sen")


def assert_no_leak(names: Sequence[str]) -> None:
    bad = [n for n in names if any(m in n.lower() for m in _LEAK_MARKERS)]
    if bad:
        raise ValueError(f"target-leaking features: {bad}")


assert_no_leak(FEATURE_NAMES)


def _f(x: float | None, fn: object = None) -> float:
    if x is None:
        return math.nan
    return float(fn(x)) if fn else float(x)  # type: ignore[operator]


def region_vector(r: RegionFeatures) -> list[float]:
    lat, lon = math.radians(r.lat), math.radians(r.lon)
    return [
        math.sin(lat),
        math.cos(lat),
        math.sin(lon),
        math.cos(lon),
        abs(r.lat),
        math.log10(r.area_km2),
        _f(r.coast_share),
        _f(r.dist_to_sea_km, lambda v: math.log10(1 + v)),
        _f(r.elev_mean_m),
        _f(r.elev_range_m),
        *(r.land_cover.get(c, math.nan) if r.land_cover else math.nan for c in LAND_COVER_CLASSES),
        _f(r.clim_t_c),
        _f(r.clim_pr_mm_yr, lambda v: math.log10(1 + v)),
        _f(r.clim_ndvi),
        _f(r.seasonal_amplitude_c),
        _f(r.aridity_index),
        float(KOPPEN.index(r.koppen[0].upper()))
        if r.koppen and r.koppen[0].upper() in KOPPEN
        else math.nan,
        _f(r.pop_density, lambda v: math.log10(1 + v)),
        _f(r.pop_change_pct),
        _f(r.built_share),
    ]


class Vocab:
    """Integer codes of categorical values, fixed at training time."""

    def __init__(self, data: dict[str, list[str]] | None = None) -> None:
        self.data: dict[str, list[str]] = data or {
            "variable": [],
            "concept": [],
            "domain": [],
        }

    @classmethod
    def fit(cls, variables: Sequence[VariableInfo]) -> Vocab:
        return cls(
            {
                "variable": sorted({v.variable_id for v in variables}),
                "concept": sorted({v.concept_id for v in variables}),
                "domain": sorted({v.domain for v in variables}),
            }
        )

    def code(self, field: str, value: str) -> float:
        vals = self.data[field]
        return float(vals.index(value)) if value in vals else math.nan


def build_matrix(
    rows: Sequence[tuple[RegionFeatures, VariableInfo, str]], vocab: Vocab
) -> NDArray[np.float64]:
    """(region, variable, season) rows -> X of shape (n, len(FEATURE_NAMES))."""
    cache: dict[str, list[float]] = {}
    out = np.empty((len(rows), len(FEATURE_NAMES)))
    for k, (reg, var, season) in enumerate(rows):
        rv = cache.get(reg.region_id)
        if rv is None:
            rv = cache[reg.region_id] = region_vector(reg)
        out[k] = [
            *rv,
            _f(var.record_years),
            _f(var.noise_level),
            vocab.code("variable", var.variable_id),
            vocab.code("concept", var.concept_id),
            vocab.code("domain", var.domain),
            float(SEASONS.index(season)),
        ]
    return out


def reason_for(feature: str, value: float) -> ReasonCode | None:
    """Reason code for a feature that pushed ``p_significant`` up, given its value.

    The text built from it states association only ("in similar regions trends are more
    common"), never cause (section 11.3).
    """
    v = value
    nan = not math.isfinite(v)
    if feature in ("variable_code", "concept_code", "domain_code"):
        return "variable_prior"
    if feature == "season_code":
        return "season_prior"
    if nan:
        return None
    # Latitude: abs_lat in degrees, lat_cos = cos(lat) (55 deg -> 0.57, 23.5 deg -> 0.92).
    if feature == "abs_lat" or feature == "lat_cos":
        deg = v if feature == "abs_lat" else math.degrees(math.acos(min(1.0, max(-1.0, v))))
        if deg >= 55:
            return "high_latitude"
        if deg < 23.5:
            return "tropical"
        return None
    table: dict[str, tuple[float, ReasonCode, ReasonCode | None]] = {
        # feature: (threshold, code if above, code if below)
        "aridity_index": (0.5, "humid_climate", "arid_climate"),
        "lc_barren": (0.3, "desert_cover", None),
        "clim_t_c": (20.0, "hot_climate", None),
        "coast_share": (0.2, "coastal", "inland"),
        "log_dist_to_sea": (math.log10(1 + 300), "inland", "coastal"),
        "elev_range_m": (1500.0, "mountainous", "lowland"),
        "lc_forest": (0.4, "forest_cover", None),
        "lc_cropland": (0.3, "cropland", None),
        "lc_urban": (0.1, "urban_area", None),
        "built_share": (0.1, "urban_area", None),
        "pop_change_pct": (15.0, "rapid_urban_growth", None),
        "log_pop_density": (math.log10(1 + 300), "dense_population", None),
        "log_area": (5.0, "large_region", "small_region"),
        "seasonal_amplitude_c": (20.0, "strong_seasonality", None),
        "record_years": (30.0, "long_record", "short_record"),
        "noise_level": (1.0, "noisy_variable", None),
        "lc_snow_ice": (0.2, "cold_climate", None),
    }
    if feature == "clim_t_c" and v < 0:
        return "cold_climate"
    if feature in table:
        thr, above, below = table[feature]
        return above if v >= thr else below
    return None
