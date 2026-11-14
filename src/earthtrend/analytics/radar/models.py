"""Models of the Radar of trends (docs/PLAN_ANALYTICS.md section 9, stage A8).

Stage 1 gives a ``RadarCandidate`` for every (variable, region, season) series; stage 2
gives a ``RadarEntry`` (full evidence protocol) for the top N candidates. Feeds are lists
of entry keys. Everything is codes and numbers, never sentences.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from earthtrend.analytics import config
from earthtrend.analytics.models import (
    AiOpinion,
    AnalysisOptions,
    Changepoint,
    Direction,
    RegionalSeries,
    Season,
    SensorEvent,
    SplitResult,
    VerdictCode,
)

FeedName = Literal[
    "strongest", "opposite", "accelerating", "breakpoints", "almost", "stable", "ai_flagged"
]
FEED_NAMES: tuple[FeedName, ...] = (
    "strongest",
    "opposite",
    "accelerating",
    "breakpoints",
    "almost",
    "stable",
    "ai_flagged",
)
Novelty = Literal["new", "upgraded", "downgraded", "unchanged"]
ALL_SEASONS: tuple[Season, ...] = ("annual", "DJF", "MAM", "JJA", "SON")

# Batch interface of M1 TrendNet (stage A6). It gets the series of one season and returns
# one opinion per series (None where it abstains). No model -> pass ``ai=None``.
AiDetective = Callable[[Sequence[RegionalSeries], AnalysisOptions], Sequence[AiOpinion | None]]


def radar_key(variable_id: str, region_id: str, season: str) -> str:
    return f"{variable_id}|{region_id}|{season}"


class RadarOptions(BaseModel):
    seasons: list[Season] = Field(default_factory=lambda: list(ALL_SEASONS))
    period: tuple[int, int] | None = None
    baseline: tuple[int, int] | None = None
    alpha: float = Field(default=config.ALPHA, gt=0.0, lt=0.5)  # stage 2 protocol
    fdr_alpha: float = Field(default=config.FDR_ALPHA, gt=0.0, lt=1.0)  # stage 1 BH
    min_years: int | None = None  # None -> each series' meta.min_years_for_trend
    top_n: int = Field(default=2000, ge=0)
    changepoints: bool = True  # BEAST in stage 2 (needed by the ``breakpoints`` feed)
    # Stage 2 priority: (1 - q_variable) * min(snr / SNR_STRONG, 2) + bonus if AI disagrees.
    ai_disagree_bonus: float = 0.5
    # radar_score bonuses (section 9.3), in strength points (0..100 scale).
    bonus_split: float = 10.0
    bonus_accelerating: float = 10.0
    bonus_new_breakpoint: float = 10.0
    # Feeds (section 9.4).
    breakpoint_prob: float = 0.7
    breakpoint_recent_years: float = 5.0
    sensor_window_months: int = 12
    almost_years: float = 10.0  # on years_to_detect_remaining
    stable_halfwidth_snr: float = config.SNR_MODERATE  # |CI bound| <= this * sigma_anom
    ai_step_prob: float = 0.5  # P(step) + P(trend_plus_step) for ``ai_flagged``
    feed_limit: int | None = 50  # per feed; None = no limit
    typology: bool = True
    seed: int = 42


class RadarSeries(BaseModel):
    """One scan input: a regional series plus what stage 2 needs to judge it."""

    series: RegionalSeries
    witnesses: list[RegionalSeries] = Field(default_factory=list)
    sensor_events: list[SensorEvent] = Field(default_factory=list)
    splits: dict[str, SplitResult] = Field(default_factory=dict)  # by season
    region_group: str | None = None  # related regions for the ``opposite`` feed


class RadarCandidate(BaseModel):
    """Stage 1 result: Sen + MK-AR1 + SNR on annual / seasonal means, FDR q-values."""

    key: str
    variable_id: str
    concept_id: str
    dataset_id: str
    region_id: str
    region_group: str | None = None
    season: Season
    region_area_km2: float | None = None
    n_years: int
    first_year: int | None = None
    last_year: int | None = None
    slope_per_decade: float | None = None  # Sen on annual (seasonal) means of anomalies
    ci95: tuple[float, float] | None = None
    p_mk: float | None = None
    z_mk: float | None = None
    sigma_anom: float | None = None
    snr: float | None = None
    signed_snr: float | None = None
    q_variable: float | None = None  # BH within the variable (all its regions and seasons)
    q_global: float | None = None  # BH over the whole scan
    sig_variable: bool = False
    sig_global: bool = False
    skipped: str | None = None  # code why stage 1 could not test the series
    ai_class: str | None = None
    ai_step_prob: float | None = None
    ai_confidence: str | None = None
    ai_disagrees: bool = False
    priority: float = 0.0


class RadarEntry(BaseModel):
    """Stage 2 result for one candidate: the full protocol, score, novelty and feeds."""

    key: str
    candidate: RadarCandidate
    verdict: VerdictCode
    strength: int
    direction: Direction
    caveats: list[str]
    items: dict[str, str]  # evidence item key -> status
    primary_slope_per_decade: float | None
    primary_ci95: tuple[float, float] | None
    sigma_anom: float | None
    snr: float | None
    years_to_detect: float | None
    years_to_detect_remaining: float | None
    shape: str | None  # NonlinearResult.shape
    changepoints: list[Changepoint] = Field(default_factory=list)
    recent_breakpoint: Changepoint | None = None
    new_breakpoint: bool = False
    split_flag: bool = False
    ai_opinion: AiOpinion | None = None
    radar_score: float = 0.0
    score_parts: dict[str, float] = Field(default_factory=dict)
    novelty: Novelty = "new"
    previous_verdict: VerdictCode | None = None
    opposite_of: list[str] = Field(default_factory=list)  # candidate keys of opposite sign
    feeds: list[FeedName] = Field(default_factory=list)


class RadarFeeds(BaseModel):
    """Entry keys per feed, best first."""

    strongest: list[str] = Field(default_factory=list)
    opposite: list[str] = Field(default_factory=list)
    accelerating: list[str] = Field(default_factory=list)
    breakpoints: list[str] = Field(default_factory=list)
    almost: list[str] = Field(default_factory=list)
    stable: list[str] = Field(default_factory=list)
    ai_flagged: list[str] = Field(default_factory=list)


class TypologyCluster(BaseModel):
    id: int
    code: str  # sign pattern, e.g. "air_temperature_2m+|precipitation-"; "no_change"
    signs: dict[str, int]  # variable -> -1 / 0 / 1 (centroid signed SNR vs SNR_MODERATE)
    centroid_snr: dict[str, float]  # mean signed SNR of the members
    size: int


class TypologyResult(BaseModel):
    """Change typology (section 8.5): clusters of units by signed SNR of several variables."""

    method: Literal["kmeans", "hdbscan"]
    season: str | None = None
    variables: list[str]
    k: int
    silhouette: float | None
    clusters: list[TypologyCluster]
    assignments: dict[str, int]  # unit id (region or cell) -> cluster id (-1 = noise)


class RadarRun(BaseModel):
    options: RadarOptions
    n_series: int
    n_tested: int
    n_sig_variable: int
    n_sig_global: int
    candidates: list[RadarCandidate]  # all of stage 1 (labels for M2, section 9.5)
    entries: list[RadarEntry]  # stage 2, by radar_score
    feeds: RadarFeeds
    dropped: list[str] = Field(default_factory=list)  # keys of the previous run not seen now
    typology: TypologyResult | None = None
    ai_model_version: str | None = None
    warnings: list[str] = Field(default_factory=list)
    timings_s: dict[str, float] = Field(default_factory=dict)
    analytics_version: str = config.ANALYTICS_VERSION

    def entry(self, key: str) -> RadarEntry | None:
        return next((e for e in self.entries if e.key == key), None)
