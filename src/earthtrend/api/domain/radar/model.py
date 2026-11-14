"""Radar: precomputed cards from the analytics scan. A feed is only a filter over those cards.

The backend never recomputes a slope or a verdict. It only refuses rows that break the feed rules,
so an inconsistent product row never reaches a reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FEEDS = frozenset(
    {"strongest", "opposite", "accelerating", "breakpoints", "almost", "stable", "ai_flagged"}
)
SEASONS = frozenset({"annual", "DJF", "MAM", "JJA", "SON"})
NOVELTY = frozenset({"new", "upgraded", "downgraded", "unchanged"})
DIRECTIONS = frozenset({"increasing", "decreasing", "none"})
VERDICT_LEVELS = frozenset({"proven", "strong", "likely", "suspicious", "no_evidence", "inadmissible"})
SIGNIFICANT = frozenset({"proven", "strong", "likely"})
MAX_PAGE_SIZE = 100
ALMOST_MAX_YEARS = 10.0


class RadarError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def require_feed(feed: str) -> str:
    if feed not in FEEDS:
        raise RadarError("feed_invalid", "Невідома стрічка радару")
    return feed


def require_season(season: str | None) -> str | None:
    if season is not None and season not in SEASONS:
        raise RadarError("season_invalid", "Сезон має бути annual, DJF, MAM, JJA або SON")
    return season


def require_page(page: int, page_size: int) -> None:
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise RadarError("page_invalid", f"Сторінка від 1, розмір від 1 до {MAX_PAGE_SIZE}")


def _feed_allows(item: RadarItem) -> bool:
    """Feed rules of the analytics scan (PLAN_ANALYTICS §9.4), checked, not recomputed."""
    level = item.verdict_level
    if item.feed == "strongest":
        return level in {"proven", "strong"}
    if item.feed == "almost":
        return level == "suspicious" and item.years_to_detect is not None and item.years_to_detect <= ALMOST_MAX_YEARS
    if item.feed == "stable":
        return level == "no_evidence"
    if item.feed == "opposite":
        return item.split_flag or level in SIGNIFICANT
    if item.feed == "ai_flagged":
        return level not in {"no_evidence", "inadmissible"}
    return level in SIGNIFICANT  # accelerating, breakpoints


@dataclass(frozen=True)
class RadarItem:
    id: str
    feed: str
    variable_id: str
    region_id: str
    direction: str
    slope_decade: float
    pct_decade: float
    snr: float
    p_mk: float
    p_ols: float
    q_fdr: float
    split_flag: bool
    score: float
    verdict_level: str
    case_id: str
    season: str = "annual"
    novelty: str = "unchanged"
    years_to_detect: float | None = None
    area_km2: float = 0.0

    def __post_init__(self) -> None:
        require_feed(self.feed)
        require_season(self.season)
        if self.direction not in DIRECTIONS:
            raise RadarError("item_invalid", "Напрям має бути increasing, decreasing або none")
        if self.verdict_level not in VERDICT_LEVELS:
            raise RadarError("item_invalid", "Невідомий рівень вироку")
        if self.novelty not in NOVELTY:
            raise RadarError("item_invalid", "Невідома новизна")
        if not all(0.0 <= value <= 1.0 for value in (self.p_mk, self.p_ols, self.q_fdr)):
            raise RadarError("item_invalid", "p і q мають бути від 0 до 1")
        if not _feed_allows(self):
            raise RadarError("item_invalid", f"Рядок не відповідає правилу стрічки {self.feed}")

    @property
    def case_url(self) -> str:
        return f"/api/v1/cases/{self.case_id}"


@dataclass(frozen=True)
class TypologyCluster:
    """Cells with a similar sign pattern of several variables. A reading of the radar, not a root."""

    id: str
    pattern: str
    signs: dict[str, int]
    season: str = "annual"
    area_km2: float = 0.0
    region_ids: tuple[str, ...] = ()
    geometry: dict | None = None

    def __post_init__(self) -> None:
        require_season(self.season)
        if not self.signs or any(sign not in (-1, 0, 1) for sign in self.signs.values()):
            raise RadarError("cluster_invalid", "Знаки кластера мають бути -1, 0 або 1")

    def covers(self, variables: list[str] | None) -> bool:
        return not variables or all(variable in self.signs for variable in variables)


@dataclass(frozen=True)
class RadarPage:
    items: list[RadarItem]
    page: int
    page_size: int
    total: int
    version: str
    generated_at: str


@dataclass(frozen=True)
class RadarProduct:
    version: str
    generated_at: str
    items: tuple[RadarItem, ...] = ()
    clusters: tuple[TypologyCluster, ...] = field(default_factory=tuple)

    def page(
        self,
        *,
        feed: str,
        variable_id: str | None = None,
        region_id: str | None = None,
        season: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RadarPage:
        require_feed(feed)
        require_season(season)
        require_page(page, page_size)
        matched = sorted(
            (
                item
                for item in self.items
                if item.feed == feed
                and (variable_id is None or item.variable_id == variable_id)
                and (region_id is None or item.region_id == region_id)
                and (season is None or item.season == season)
            ),
            key=lambda item: (-item.score, item.id),
        )
        start = (page - 1) * page_size
        return RadarPage(
            items=matched[start : start + page_size],
            page=page,
            page_size=page_size,
            total=len(matched),
            version=self.version,
            generated_at=self.generated_at,
        )

    def typology(self, *, variables: list[str] | None = None, season: str | None = None) -> list[TypologyCluster]:
        require_season(season)
        return [
            cluster
            for cluster in self.clusters
            if cluster.covers(variables) and (season is None or cluster.season == season)
        ]
