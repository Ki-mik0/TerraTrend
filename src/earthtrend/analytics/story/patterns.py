"""Pattern library of Story Lens (docs/PLAN_ANALYTICS.md section 10.3).

A pattern is a list of conditions on concept trends. A condition has one or more options
(OR): concept, accepted directions, optional season, optional context requirement.

Scoring of a condition (best option wins):
* met by a significant trend in an accepted direction -> its evidence strength (0..1);
* met by "no significant change" where "flat" is accepted -> ``FLAT_SCORE`` (absence of a
  trend is weaker support than a proven trend);
* data present but not met -> 0;
* no data for any option -> not counted (``met = None``).

A pattern matches when every required condition is met. ``confidence`` = mean score over
the counted conditions ("share of met conditions weighted by evidence strength").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from earthtrend.analytics.story.models import (
    ConceptTrend,
    ConditionResult,
    PatternContext,
    PatternMatch,
    TrendSign,
)

FLAT_SCORE = 0.5
MIN_CONFIDENCE = 0.0  # report every pattern whose required conditions hold


@dataclass(frozen=True)
class Option:
    concept: str
    accept: tuple[str, ...]  # subset of "up", "down", "flat"
    season: str | None = None  # None: the story's season, then annual
    context: str | None = None  # PatternContext flag that must be true


@dataclass(frozen=True)
class Condition:
    code: str
    options: tuple[Option, ...]
    required: bool = True


@dataclass(frozen=True)
class Pattern:
    code: str
    conditions: tuple[Condition, ...]


T = "air_temperature"

PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        "aridification",
        (
            Condition("temperature_up", (Option(T, ("up",)),)),
            Condition("precipitation_down_or_flat", (Option("precipitation", ("down", "flat")),)),
            Condition(
                "soil_moisture_down",
                (
                    Option("soil_moisture_root_zone", ("down",)),
                    Option("soil_moisture_surface", ("down",)),
                ),
            ),
            Condition(
                "et_up_or_ndvi_down",
                (Option("evapotranspiration", ("up",)), Option("ndvi", ("down",))),
                required=False,
            ),
        ),
    ),
    Pattern(
        "greening",
        (
            Condition("ndvi_up", (Option("ndvi", ("up",)),)),
            Condition(
                "water_or_cold_warming",
                (
                    Option("precipitation", ("up",)),
                    Option(T, ("up",), context="cold_region"),
                ),
            ),
        ),
    ),
    Pattern(
        "earlier_spring",
        (
            Condition("growing_season_up", (Option("growing_season_length", ("up",)),)),
            Condition("spring_temperature_up", (Option(T, ("up",), season="MAM"),)),
            Condition(
                "snow_season_down",
                (Option("snow_days", ("down",)), Option("snow_cover", ("down",))),
                required=False,
            ),
        ),
    ),
    Pattern(
        "snow_retreat",
        (
            Condition(
                "snow_down",
                (
                    Option("snow_water_equivalent", ("down",)),
                    Option("snow_days", ("down",)),
                    Option("snow_cover", ("down",)),
                ),
            ),
            Condition("temperature_up", (Option(T, ("up",)),)),
        ),
    ),
    Pattern(
        "cleaner_air",
        (
            Condition("no2_down", (Option("no2", ("down",)),)),
            Condition("aod_down", (Option("aerosol_optical_depth", ("down",)),), required=False),
        ),
    ),
    Pattern(
        "worsening_air",
        (
            Condition("no2_up", (Option("no2", ("up",)),)),
            Condition("aod_up", (Option("aerosol_optical_depth", ("up",)),), required=False),
        ),
    ),
    Pattern(
        "urban_heating",
        (Condition("city_minus_ring_up", (Option("urban_heat_contrast", ("up",)),)),),
    ),
    Pattern(
        "ocean_warming",
        (Condition("sst_up", (Option("sea_surface_temperature", ("up",)),)),),
    ),
    Pattern(
        "troposphere_warming_stratosphere_cooling",
        (
            Condition("troposphere_up", (Option("air_temperature_upper", ("up",)),)),
            Condition("stratosphere_down", (Option("stratosphere_temperature", ("down",)),)),
        ),
    ),
)


def _lookup(
    trends: dict[tuple[str, str], ConceptTrend], opt: Option, season: str
) -> ConceptTrend | None:
    if opt.season is not None:
        return trends.get((opt.concept, opt.season))
    return trends.get((opt.concept, season)) or trends.get((opt.concept, "annual"))


def _score_option(tr: ConceptTrend, opt: Option) -> tuple[bool, float, TrendSign]:
    seen: TrendSign = tr.direction if tr.significant else "none"
    if seen in opt.accept:
        return True, tr.strength, seen
    if seen == "none" and "flat" in opt.accept:
        return True, FLAT_SCORE, seen
    return False, 0.0, seen


def evaluate_pattern(
    pattern: Pattern,
    trends: dict[tuple[str, str], ConceptTrend],
    season: str = "annual",
    context: PatternContext | None = None,
) -> PatternMatch | None:
    """None when a required condition fails or has no data."""
    ctx = context or PatternContext()
    results: list[ConditionResult] = []
    for cond in pattern.conditions:
        best: ConditionResult | None = None
        for opt in cond.options:
            if opt.context is not None and not getattr(ctx, opt.context):
                continue
            tr = _lookup(trends, opt, season)
            if tr is None:
                continue
            met, score, seen = _score_option(tr, opt)
            cand = ConditionResult(
                code=cond.code,
                required=cond.required,
                met=met,
                score=round(score, 4),
                concept_used=opt.concept,
                seen=seen,
            )
            if best is None or (cand.met, cand.score) > (bool(best.met), best.score):
                best = cand
        if best is None:
            best = ConditionResult(code=cond.code, required=cond.required, met=None, score=0.0)
        if cond.required and not best.met:
            return None
        results.append(best)
    counted = [r for r in results if r.met is not None]
    conf = sum(r.score for r in counted) / len(counted) if counted else 0.0
    return PatternMatch(
        code=pattern.code,
        confidence=round(conf, 4),
        conditions=results,
        n_counted=len(counted),
    )


def match_patterns(
    trends: Sequence[ConceptTrend],
    season: str = "annual",
    context: PatternContext | None = None,
    library: Sequence[Pattern] = PATTERNS,
    min_confidence: float = MIN_CONFIDENCE,
) -> list[PatternMatch]:
    """All matching patterns, by confidence (ties: code)."""
    table: dict[tuple[str, str], ConceptTrend] = {}
    for tr in trends:
        key = (tr.concept_id, tr.season)
        old = table.get(key)
        if old is None or tr.strength > old.strength:  # strongest evidence per concept/season
            table[key] = tr
    out = [
        m
        for p in library
        if (m := evaluate_pattern(p, table, season, context)) is not None
        and m.confidence >= min_confidence
    ]
    out.sort(key=lambda m: (-m.confidence, m.code))
    return out


__all__ = [
    "PATTERNS",
    "Condition",
    "Option",
    "Pattern",
    "evaluate_pattern",
    "match_patterns",
]
