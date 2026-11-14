"""Input and output models of the analytics core (docs/PLAN_ANALYTICS.md section 3).

These models are the shared language with the API and, through OpenAPI, the web app.
Analytics returns codes (flags, caveats, verdicts), never ready-made sentences.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from earthtrend.analytics import config

Season = Literal["annual", "DJF", "MAM", "JJA", "SON"]
Direction = Literal["increasing", "decreasing", "none"]
VerdictCode = Literal["proven", "strong", "likely", "suspicious", "no_evidence", "inadmissible"]
ItemKey = Literal[
    "statistics", "magnitude", "witnesses", "robustness", "alibi", "quality", "ai_expert"
]
ItemStatus = Literal["pass", "partial", "fail", "na"]


# ---------------------------------------------------------------- input


class SeriesMeta(BaseModel):
    variable_id: str
    concept_id: str
    dataset_id: str
    dataset_version: str
    units: str
    region_id: str
    ratio_scale: bool = False
    transform: Literal["none", "log"] = "none"
    distribution: Literal["symmetric", "skewed", "zero_inflated"] = "symmetric"
    region_area_km2: float | None = None
    frequency: Literal["daily", "monthly"] = "monthly"
    # Daily -> monthly rule (section 4.1): mean (temperature), sum (precipitation), max/min.
    aggregation: Literal["mean", "sum", "max", "min"] = "mean"
    min_years_for_trend: int = config.DEFAULT_MIN_YEARS


class RegionalSeries(BaseModel):
    """Regional mean series; ``None`` is a gap.

    Monthly series use first days of months. Daily series (``meta.frequency == "daily"``)
    are aggregated to months first (section 4.1).
    """

    meta: SeriesMeta
    dates: list[date]
    values: list[float | None]
    coverage: list[float] | None = None
    stable_fraction: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> RegionalSeries:
        if len(self.values) != len(self.dates):
            raise ValueError("values and dates must have the same length")
        if self.coverage is not None and len(self.coverage) != len(self.dates):
            raise ValueError("coverage and dates must have the same length")
        if any(b <= a for a, b in zip(self.dates, self.dates[1:], strict=False)):
            raise ValueError("dates must be strictly increasing")
        return self


class AnalysisOptions(BaseModel):
    period: tuple[int, int] | None = None  # inclusive years
    season: Season = "annual"
    baseline: tuple[int, int] | None = None  # climatology years; default = whole period
    alpha: float = Field(default=config.ALPHA, gt=0.0, lt=0.5)
    nonlinear: bool = True  # P-spline curve and acceleration test (cheap)
    seasonal_breakdown: bool = True  # trend per calendar month with FDR (annual season only)
    changepoints: bool = False  # BEAST; ~0.1 s, the "compute" path (section 14)
    bootstrap: bool = False  # moving-block bootstrap CI ("Expert" and disputed cases)
    n_boot: int = Field(default=2000, ge=100, le=20_000)
    expert: bool = False  # "Expert" mode: adds STL decomposition, GLSAR and bootstrap
    ai_opinion: bool = True  # run M1 when an active model exists (stage A6; none yet)
    seed: int = 42


# ---------------------------------------------------------------- output


class TrendTest(BaseModel):
    method: Literal["ols_ar1", "ols_ar1_annual", "mk_ar1", "sen", "glsar"]
    slope_per_decade: float | None
    ci95: tuple[float, float] | None
    p_value: float | None
    statistic: float | None
    n: int
    n_eff: float | None = None


class Magnitude(BaseModel):
    slope_per_decade: float
    percent_per_decade: float | None = None  # only for log transform / ratio_scale
    sigma_anom: float
    snr: float
    snr_class: Literal["weak", "moderate", "strong"]


class QualityFlag(BaseModel):
    code: str
    details: dict[str, Any] = Field(default_factory=dict)


class SeriesPayload(BaseModel):
    """Everything the main chart needs, aligned on ``dates``."""

    dates: list[date]
    values: list[float | None]  # original units
    anomalies: list[float | None]
    trend: list[float]  # Sen line on anomalies
    ci_low: list[float]  # slope-uncertainty band (95%)
    ci_high: list[float]


class Verdict(BaseModel):
    code: VerdictCode
    strength: int = Field(ge=0, le=100)
    ruleset: str = config.VERDICT_RULESET
    direction: Direction
    caveats: list[str] = Field(default_factory=list)


class AiOpinion(BaseModel):
    """Opinion of M1 TrendNet (section 3.3, 6.7). Advisory: never enters the verdict."""

    model_version: str
    class_probs: dict[str, float]  # no_trend, linear, step, accelerating, trend_plus_step
    predicted_class: str
    slope_per_decade: float
    slope_pi90: tuple[float, float]
    changepoint_probs: list[float] | None = None
    confidence: Literal["high", "medium", "low"]
    agrees_with_statistics: bool


class StlResult(BaseModel):
    """Robust STL decomposition (period 12) of the monthly series, for charts only (4.3)."""

    dates: list[date]
    trend: list[float | None]
    seasonal: list[float | None]
    resid: list[float | None]


class Changepoint(BaseModel):
    """Change in the trend component (section 5.6)."""

    at: date
    probability: float | None  # BEAST posterior; None for the PELT fallback
    ci: tuple[date, date] | None
    jump: float | None  # abrupt change of level at the point, analysis units
    method: Literal["beast", "pelt"]


class MonthTrend(BaseModel):
    """Trend of one calendar month across years (section 5.8)."""

    month: int = Field(ge=1, le=12)
    slope_per_decade: float | None
    ci95: tuple[float, float] | None
    p_mk: float | None
    q_value: float | None  # Benjamini-Hochberg over the 12 months
    significant: bool
    n_years: int


class NonlinearResult(BaseModel):
    """Penalized spline on annual means: curve, derivative, acceleration (section 5.5)."""

    years: list[int]
    curve: list[float]
    curve_low: list[float]
    curve_high: list[float]
    derivative_per_decade: list[float]
    derivative_low: list[float]
    derivative_high: list[float]
    edf: float  # effective degrees of freedom of the spline
    smoothing: float  # lambda chosen by GCV
    aic_linear: float
    aic_spline: float
    delta_aic: float  # aic_linear - aic_spline; >= 4 favours the curve
    change_z: float  # (late third - early third) mean derivative, in trend direction
    shape: Literal["linear", "accelerating", "decelerating", "nonlinear"]


class BootstrapResult(BaseModel):
    """Moving-block bootstrap of OLS residuals (section 5.4)."""

    slope_ci95_per_decade: tuple[float, float]
    block_length: int
    n_boot: int
    seed: int


class TrendResult(BaseModel):
    meta: SeriesMeta
    options: AnalysisOptions
    period_used: tuple[date, date] | None
    n_used: int
    years_of_data: float
    tests: list[TrendTest]
    primary_slope_per_decade: float | None  # Sen's slope
    primary_ci95: tuple[float, float] | None
    direction: Direction
    magnitude: Magnitude | None
    years_to_detect: float | None
    years_to_detect_remaining: float | None
    flags: list[QualityFlag]
    series_out: SeriesPayload
    verdict: Verdict
    nonlinear: NonlinearResult | None = None
    changepoints: list[Changepoint] = Field(default_factory=list)
    seasonal_breakdown: list[MonthTrend] = Field(default_factory=list)
    influence: JackknifeResult | None = None
    bootstrap: BootstrapResult | None = None
    stl: StlResult | None = None
    ai_opinion: AiOpinion | None = None
    # Every number a text (Story Lens, assistant, verdict card) may quote; the backend
    # checks generated texts against these facts (section 3.3, Plan_Backend domain rules).
    summary_text_facts: dict[str, Any] = Field(default_factory=dict)
    analytics_version: str = config.ANALYTICS_VERSION
    model_versions: dict[str, str] = Field(default_factory=dict)

    def test(self, method: str) -> TrendTest | None:
        return next((t for t in self.tests if t.method == method), None)


# ---------------------------------------------------------------- spatial (section 8)


class SplitResult(BaseModel):
    """Area shares of a region by significant sign (section 8.3)."""

    sig_pos: float
    sig_neg: float
    nonsig: float
    split_flag: bool


class Zone(BaseModel):
    """Connected patch of significant cells of one sign (section 8.4)."""

    id: int
    sign: Literal[-1, 1]
    n_cells: int
    area_km2: float
    area_share: float  # of the analysed area
    mean_slope_per_decade: float  # area-weighted
    centroid: tuple[float, float]  # (lat, lon)
    bbox: tuple[float, float, float, float]  # (lat_min, lon_min, lat_max, lon_max)


class GridSummary(BaseModel):
    """JSON part of a grid product: everything except the per-cell arrays."""

    n_cells_valid: int
    n_cells_significant: int
    fdr_alpha: float
    p_threshold: float | None  # largest p that passed BH; None if no cell passed
    area_weighted_mean_slope_per_decade: float | None
    split: SplitResult
    zones: list[Zone]
    analytics_version: str = config.ANALYTICS_VERSION


# ---------------------------------------------------------------- evidence protocol (section 6)


class JackknifeResult(BaseModel):
    """Leave-one-year-out Sen slope and MK on annual means (section 5.9)."""

    years: list[int]
    slope_per_decade: list[float | None]  # slope without that year
    p_mk: list[float | None]
    full_slope_per_decade: float
    full_p_mk: float
    max_rel_change: float
    most_influential_year: int | None
    significance_lost_year: int | None
    influential: bool


class WitnessDataset(BaseModel):
    dataset_id: str
    slope_per_decade: float | None
    p_mk: float | None
    significant: bool


class WitnessPair(BaseModel):
    a: str
    b: str
    diff_slope_per_decade: float | None  # trend of a - b
    p_mk: float | None
    p_ols: float | None
    diverge: bool


class WitnessesResult(BaseModel):
    common_period: tuple[date, date] | None
    datasets: list[WitnessDataset]
    pairs: list[WitnessPair]


class TriangleResult(BaseModel):
    """Trends for all (start, end) windows on annual means (section 6.3)."""

    years: list[int]
    min_window: int
    slope_per_decade: list[list[float | None]]  # [start][end]; None outside the triangle
    p_mk: list[list[float | None]]
    n_windows: int
    same_sign_share: float
    sig_same_sign_share: float


class ClimateIndex(BaseModel):
    """Monthly climate index used as an alibi (Nino 3.4, NAO/AO, volcanic AOD)."""

    name: Literal["nino34", "nao", "ao", "volcanic_aod"]
    dates: list[date]
    values: list[float | None]

    @model_validator(mode="after")
    def _check(self) -> ClimateIndex:
        if len(self.values) != len(self.dates):
            raise ValueError("values and dates must have the same length")
        return self


class AlibiTerm(BaseModel):
    index: str
    lag_months: int
    coefficient: float
    trend_overlap_r: float  # corr(index, time) over the analysis period


class AlibiResult(BaseModel):
    """Trend with and without climate indices (section 6.4)."""

    b_raw_per_decade: float
    b_adjusted_per_decade: float
    p_adjusted: float
    se_adjusted_hac: float
    partial_r2: float
    terms: list[AlibiTerm]  # indices kept by block cross-validation
    rejected: list[str]  # indices that did not improve held-out years
    adjusted_anomalies: list[float | None]  # "series without alibi", aligned with dates
    dates: list[date]


class SensorEvent(BaseModel):
    """Launch, degradation or version change of an instrument (catalog/sensor_events.yaml)."""

    date: date
    code: str


class EvidenceItem(BaseModel):
    key: ItemKey
    status: ItemStatus
    score: float = Field(ge=0.0, le=1.0)
    advisory: bool = False  # True for ai_expert: never enters the verdict
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceProtocol(BaseModel):
    items: list[EvidenceItem]
    verdict: VerdictCode
    strength: int = Field(ge=0, le=100)
    ruleset: str
    direction: Direction
    caveats: list[str]
    analytics_version: str = config.ANALYTICS_VERSION

    def item(self, key: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.key == key), None)


TrendResult.model_rebuild()
