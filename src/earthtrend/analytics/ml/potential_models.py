"""Contracts of M2 TrendPotential, the "Informant" (docs/PLAN_ANALYTICS.md sections 3.3, 11.3).

Region features are a precomputed product: the backend aggregates land cover, relief,
climate and population rasters over the region and passes the numbers in (section 17).
Analytics never reads those rasters itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from earthtrend.analytics.models import Season

ReasonCode = Literal[
    "high_latitude",
    "tropical",
    "arid_climate",
    "humid_climate",
    "cold_climate",
    "hot_climate",
    "coastal",
    "inland",
    "mountainous",
    "lowland",
    "forest_cover",
    "cropland",
    "desert_cover",
    "urban_area",
    "rapid_urban_growth",
    "dense_population",
    "large_region",
    "small_region",
    "strong_seasonality",
    "long_record",
    "short_record",
    "noisy_variable",
    "variable_prior",  # the variable itself trends often (no regional reason)
    "season_prior",
]

LAND_COVER_CLASSES: tuple[str, ...] = (
    "forest",
    "shrubland",
    "grassland",
    "cropland",
    "urban",
    "snow_ice",
    "barren",
    "water",
    "wetland",
)


class RegionFeatures(BaseModel):
    """Region descriptors (section 11.3 "Ознаки"). Missing ones are None (LightGBM handles
    missing values natively). Never put any trend of a target variable here (target leak)."""

    region_id: str
    lat: float = Field(ge=-90, le=90)  # area-weighted centroid
    lon: float = Field(ge=-180, le=360)
    area_km2: float = Field(gt=0)
    coast_share: float | None = Field(default=None, ge=0, le=1)
    dist_to_sea_km: float | None = Field(default=None, ge=0)
    elev_mean_m: float | None = None
    elev_range_m: float | None = Field(default=None, ge=0)
    land_cover: dict[str, float] = Field(default_factory=dict)  # MCD12C1 class -> share
    clim_t_c: float | None = None  # climatological mean temperature
    clim_pr_mm_yr: float | None = Field(default=None, ge=0)
    clim_ndvi: float | None = None
    seasonal_amplitude_c: float | None = Field(default=None, ge=0)
    aridity_index: float | None = Field(default=None, ge=0)  # P / PET; < 0.2 arid
    koppen: str | None = None  # main group letter A..E
    pop_density: float | None = Field(default=None, ge=0)  # people / km2
    pop_change_pct: float | None = None  # per decade
    built_share: float | None = Field(default=None, ge=0, le=1)


class VariableInfo(BaseModel):
    """Variable descriptors known before any analysis (section 11.3 "Змінна")."""

    variable_id: str
    concept_id: str
    domain: str  # atmosphere, land, ocean, cryosphere, composition, hydrology...
    record_years: float | None = None
    noise_level: float | None = None  # typical sigma of annual anomalies / climatological sd


class TrendPotential(BaseModel):
    """M2 forecast for one (region, variable, season) - section 3.3."""

    variable_id: str
    season: Season
    p_significant: float = Field(ge=0, le=1)  # isotonic-calibrated
    expected_sign: Literal[-1, 0, 1]
    expected_snr: tuple[float, float]  # 10th and 90th percentile of |SNR|
    top_reasons: list[ReasonCode]
    model_version: str


class PotentialPage(BaseModel):
    """Answer of ``GET /regions/{id}/potential``: ranked forecasts or a reason for none."""

    region_id: str
    items: list[TrendPotential]  # best first
    model_version: str | None
    fallback_reason: str | None = None  # no_active_model, gate_not_passed, load_error
