"""``StoryFacts`` (docs/PLAN_ANALYTICS.md section 10.4): every number a story may quote.

``build_story_facts`` assembles facts from results that already exist; ``story_lens`` runs
the whole chain for one case: trend + protocol -> related variables -> patterns -> facts.
The text itself is written by the backend (M4, template or external LLM) and its numbers
are checked against ``StoryFacts.numbers``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.evidence.protocol import build_protocol
from earthtrend.analytics.models import (
    AnalysisOptions,
    ClimateIndex,
    EvidenceProtocol,
    RegionalSeries,
    Season,
    SensorEvent,
    TrendResult,
)
from earthtrend.analytics.story.models import (
    AlibiFacts,
    ConceptTrend,
    MainTrendFacts,
    PatternContext,
    PatternMatch,
    ProcessGraph,
    RelatedVariable,
    StoryFacts,
    TrendSign,
    WitnessFacts,
)
from earthtrend.analytics.story.patterns import PATTERNS, match_patterns
from earthtrend.analytics.story.process_graph import default_process_graph
from earthtrend.analytics.story.related import light_options, related_variables, verdict_strength

SIGNIFICANT = ("proven", "strong", "likely")
NUMBER_DIGITS = 6


def _trend_sign(direction: str) -> TrendSign:
    return "up" if direction == "increasing" else "down" if direction == "decreasing" else "none"


def concept_trend(tr: TrendResult, protocol: EvidenceProtocol | None = None) -> ConceptTrend:
    """Pattern input from a case; the full protocol wins over the quick verdict."""
    if protocol is not None:
        verdict, direction, strength = protocol.verdict, protocol.direction, protocol.strength / 100
    else:
        verdict, direction = tr.verdict.code, tr.verdict.direction
        strength = verdict_strength(tr.verdict)
    return ConceptTrend(
        concept_id=tr.meta.concept_id,
        season=tr.options.season,
        direction=_trend_sign(direction),
        significant=verdict in SIGNIFICANT,
        strength=float(np.clip(strength, 0.0, 1.0)),
        variable_id=tr.meta.variable_id,
        slope_per_decade=tr.primary_slope_per_decade,
        verdict=verdict,
    )


def concept_trend_from_related(rv: RelatedVariable) -> ConceptTrend:
    return ConceptTrend(
        concept_id=rv.concept_id,
        season=rv.season,
        direction=_trend_sign(rv.direction),
        significant=rv.verdict in SIGNIFICANT,
        strength=rv.strength,
        variable_id=rv.variable_id,
        slope_per_decade=rv.slope_per_decade,
        verdict=rv.verdict,
    )


def _put(numbers: dict[str, float], key: str, value: Any) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float) and np.isfinite(value):
        numbers[key] = round(float(value), NUMBER_DIGITS)


def _main_facts(tr: TrendResult, protocol: EvidenceProtocol | None) -> MainTrendFacts:
    def p(method: str) -> float | None:
        t = tr.test(method)
        return t.p_value if t else None

    mag = tr.magnitude
    return MainTrendFacts(
        variable_id=tr.meta.variable_id,
        concept_id=tr.meta.concept_id,
        dataset_id=tr.meta.dataset_id,
        region_id=tr.meta.region_id,
        season=tr.options.season,
        units=tr.meta.units,
        period_start=tr.period_used[0] if tr.period_used else None,
        period_end=tr.period_used[1] if tr.period_used else None,
        years_of_data=tr.years_of_data,
        slope_per_decade=tr.primary_slope_per_decade,
        ci95=tr.primary_ci95,
        percent_per_decade=mag.percent_per_decade if mag else None,
        snr=mag.snr if mag else None,
        snr_class=mag.snr_class if mag else None,
        p_ols_annual=p("ols_ar1_annual"),
        p_ols=p("ols_ar1"),
        p_mk=p("mk_ar1"),
        years_to_detect=tr.years_to_detect,
        direction=protocol.direction if protocol else tr.verdict.direction,
        verdict=protocol.verdict if protocol else tr.verdict.code,
        strength=protocol.strength if protocol else tr.verdict.strength,
        ruleset=protocol.ruleset if protocol else tr.verdict.ruleset,
        shape=tr.nonlinear.shape if tr.nonlinear else None,
    )


def _alibi_facts(protocol: EvidenceProtocol | None) -> AlibiFacts | None:
    item = protocol.item("alibi") if protocol else None
    if item is None:
        return None
    d = item.details
    return AlibiFacts(
        status=item.status,
        b_raw_per_decade=d.get("b_raw_per_decade"),
        b_adjusted_per_decade=d.get("b_adjusted_per_decade"),
        p_adjusted=d.get("p_adjusted"),
        partial_r2=d.get("partial_r2"),
        terms=[
            {"index": t["index"], "lag_months": t["lag_months"], "coefficient": t["coefficient"]}
            for t in d.get("terms", [])
        ],
        rejected=list(d.get("rejected", [])),
    )


def _witness_facts(protocol: EvidenceProtocol | None) -> WitnessFacts | None:
    item = protocol.item("witnesses") if protocol else None
    if item is None:
        return None
    d = item.details
    return WitnessFacts(
        status=item.status,
        datasets=[
            {k: w.get(k) for k in ("dataset_id", "slope_per_decade", "p_mk", "significant")}
            for w in d.get("datasets", [])
        ],
        n_pairs_diverging=sum(bool(pr.get("diverge")) for pr in d.get("pairs", [])),
    )


def _numbers(f: StoryFacts) -> dict[str, float]:
    n: dict[str, float] = {}
    m = f.main
    for key in (
        "years_of_data",
        "slope_per_decade",
        "percent_per_decade",
        "snr",
        "p_ols_annual",
        "p_ols",
        "p_mk",
        "years_to_detect",
        "strength",
    ):
        _put(n, f"main.{key}", getattr(m, key))
    if m.ci95:
        _put(n, "main.ci95_low", m.ci95[0])
        _put(n, "main.ci95_high", m.ci95[1])
    for rv in f.related:
        pre = f"related.{rv.variable_id}"
        for key in ("slope_per_decade", "p_mk", "corr", "corr_p", "partial_corr", "partial_p"):
            _put(n, f"{pre}.{key}", getattr(rv, key))
        _put(n, f"{pre}.lag_months", rv.lag_used_months)
        if rv.ci95:
            _put(n, f"{pre}.ci95_low", rv.ci95[0])
            _put(n, f"{pre}.ci95_high", rv.ci95[1])
    for pm in f.patterns:
        _put(n, f"patterns.{pm.code}.confidence", pm.confidence)
    if f.alibi:
        for key in ("b_raw_per_decade", "b_adjusted_per_decade", "p_adjusted", "partial_r2"):
            _put(n, f"alibi.{key}", getattr(f.alibi, key))
        for t in f.alibi.terms:
            _put(n, f"alibi.{t['index']}.coefficient", t["coefficient"])
            _put(n, f"alibi.{t['index']}.lag_months", t["lag_months"])
    if f.witnesses:
        for w in f.witnesses.datasets:
            _put(n, f"witnesses.{w['dataset_id']}.slope_per_decade", w.get("slope_per_decade"))
            _put(n, f"witnesses.{w['dataset_id']}.p_mk", w.get("p_mk"))
    if f.ai_opinion:
        op = f.ai_opinion
        _put(n, "ai.slope_per_decade", op.slope_per_decade)
        _put(n, "ai.slope_pi90_low", op.slope_pi90[0])
        _put(n, "ai.slope_pi90_high", op.slope_pi90[1])
        for cls, prob in op.class_probs.items():
            _put(n, f"ai.prob.{cls}", prob)
    return n


def build_story_facts(
    tr: TrendResult,
    protocol: EvidenceProtocol | None = None,
    related: Sequence[RelatedVariable] = (),
    patterns: Sequence[PatternMatch] = (),
    graph_version: str | None = None,
) -> StoryFacts:
    caveats: list[str] = []
    for c in [*(protocol.caveats if protocol else []), *tr.verdict.caveats]:
        if c not in caveats:
            caveats.append(c)
    ai_item = protocol.item("ai_expert") if protocol else None
    facts = StoryFacts(
        main=_main_facts(tr, protocol),
        related=list(related),
        patterns=list(patterns),
        alibi=_alibi_facts(protocol),
        witnesses=_witness_facts(protocol),
        ai_opinion=tr.ai_opinion,
        ai_status=ai_item.status if ai_item else None,
        caveats=caveats,
        graph_version=graph_version,
    )
    facts.numbers = _numbers(facts)
    return facts


def _extra_season_trends(
    main: RegionalSeries,
    candidates: Sequence[RegionalSeries],
    opts: AnalysisOptions,
    have: set[tuple[str, Season]],
) -> list[ConceptTrend]:
    """Trends that pattern conditions ask for in a fixed season (e.g. spring temperature)."""
    wanted = {
        (o.concept, o.season)
        for p in PATTERNS
        for c in p.conditions
        for o in c.options
        if o.season is not None and (o.concept, o.season) not in have
    }
    pool = [main, *[c for c in candidates if c.meta.region_id == main.meta.region_id]]
    out: list[ConceptTrend] = []
    for concept, season in sorted(wanted):
        s = next((x for x in pool if x.meta.concept_id == concept), None)
        if s is None:
            continue
        o = light_options(opts, opts.period).model_copy(update={"season": season})
        out.append(concept_trend(analyze_series(s, o)))
    return out


def story_lens(
    main: RegionalSeries,
    candidates: Sequence[RegionalSeries] = (),
    graph: ProcessGraph | None = None,
    options: AnalysisOptions | None = None,
    *,
    protocol: EvidenceProtocol | None = None,
    witnesses: list[RegionalSeries] | None = None,
    indices: list[ClimateIndex] | None = None,
    sensor_events: list[SensorEvent] | None = None,
    context: PatternContext | None = None,
) -> StoryFacts:
    """Full Story Lens chain for one case. ``candidates``: series of other concepts."""
    g = graph or default_process_graph()
    opts = options or AnalysisOptions()
    tr = analyze_series(main, opts)
    prot = protocol or build_protocol(
        main, opts, witnesses=witnesses, indices=indices, sensor_events=sensor_events
    )
    related = related_variables(
        main, candidates, g, opts, main_result=tr, main_direction=prot.direction
    )
    trends = [concept_trend(tr, prot), *(concept_trend_from_related(r) for r in related)]
    have = {(t.concept_id, t.season) for t in trends}
    trends += _extra_season_trends(main, candidates, opts, have)
    patterns = match_patterns(trends, opts.season, context)
    return build_story_facts(tr, prot, related, patterns, g.version)


__all__ = [
    "build_story_facts",
    "concept_trend",
    "concept_trend_from_related",
    "story_lens",
]
