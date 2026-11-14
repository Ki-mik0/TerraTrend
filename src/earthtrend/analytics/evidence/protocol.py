"""``build_protocol``: the evidence protocol and verdict v1 for one case (section 6, stage A2).

Items: statistics, magnitude, witnesses, robustness (trend triangle), alibi, quality.
``ai_expert`` is added once M1 exists; it is advisory and never enters the verdict.
The verdict comes from a YAML ruleset (``evidence/rulesets/``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series, prepare_series
from earthtrend.analytics.evidence.alibi import alibi, alibi_caveats, alibi_status
from earthtrend.analytics.evidence.quality import (
    artifact_flags,
    long_memory,
    quality_status,
    sensor_events_in_period,
)
from earthtrend.analytics.evidence.rules import evaluate, load_ruleset
from earthtrend.analytics.evidence.triangle import trend_triangle, triangle_status
from earthtrend.analytics.evidence.witnesses import compare_witnesses, witnesses_status
from earthtrend.analytics.models import (
    AnalysisOptions,
    ClimateIndex,
    Direction,
    EvidenceItem,
    EvidenceProtocol,
    ItemKey,
    ItemStatus,
    QualityFlag,
    RegionalSeries,
    SensorEvent,
    SplitResult,
    TrendResult,
    Zone,
)
from earthtrend.analytics.preprocess.aggregate import FloatArray, annual_means, split_dates
from earthtrend.analytics.trend.changepoint import detect_changepoints
from earthtrend.analytics.trend.ols import ols_ar1
from earthtrend.analytics.trend.seasonal_mk import seasonal_mk

PARTIAL_P = 0.2
SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0, "na": 0.0}
INADMISSIBLE_FLAGS = frozenset({"short_record", "constant_series"})


def _item(key: ItemKey, status: ItemStatus, details: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(key=key, status=status, score=SCORE[status], details=details)


def _sign(x: float | None) -> int:
    return 0 if x is None or not np.isfinite(x) or x == 0 else (1 if x > 0 else -1)


def _statistics(
    tr: TrendResult,
    p_ols_annual: float | None,
    p_smk: tuple[float, float] | None,
    alpha: float,
) -> tuple[EvidenceItem, bool]:
    """Returns the item and whether the two tests disagree (methods_disagree)."""
    ols, mk = tr.test("ols_ar1"), tr.test("mk_ar1")
    assert ols is not None and mk is not None
    ann = tr.test("ols_ar1_annual")
    # Stage 4 calibration: the annual-mean OLS is the primary test (the monthly AR(1)
    # correction over-rejects under long memory); the monthly OLS is reported only.
    primary = ann if ann is not None and ann.p_value is not None else ols
    p_ols = primary.p_value if primary.p_value is not None else 1.0
    p_mk = mk.p_value if mk.p_value is not None else 1.0
    s_ols, s_mk = _sign(primary.slope_per_decade), _sign(mk.statistic)

    skewed = tr.meta.distribution in ("skewed", "zero_inflated")
    if skewed and p_smk is not None:
        # Section 6.6: for skewed data MK + seasonal MK decide; OLS is informative only.
        p_a, s_a, p_b, s_b, b_level = p_mk, s_mk, p_smk[0], _sign(p_smk[1]), alpha
    else:
        p_a, s_a, p_b, s_b, b_level = p_ols, s_ols, p_mk, s_mk, config.MK_CONFIRM_P

    if p_a < alpha and p_b < b_level and s_a == s_b != 0:
        status: ItemStatus = "pass"
    elif p_a >= PARTIAL_P and p_b >= PARTIAL_P:
        status = "fail"
    else:
        status = "partial"
    disagree = (p_a < alpha) != (p_b < b_level) or (p_a < alpha and p_b < b_level and s_a != s_b)
    details = {
        "p_ols": p_ols,
        "p_ols_monthly": ols.p_value,
        "p_ols_annual": p_ols_annual,
        "p_mk": p_mk,
        "p_seasonal_mk": p_smk[0] if p_smk else None,
        "decided_by": "mk+seasonal_mk" if skewed and p_smk else "ols_ar1_annual+mk_ar1",
        "slope_ols_per_decade": ols.slope_per_decade,
        "n_eff": ols.n_eff,
    }
    return _item("statistics", status, details), disagree


def _ai_expert(tr: TrendResult, stat_item: EvidenceItem) -> tuple[EvidenceItem | None, bool]:
    """Section 6.7: M1's opinion as an advisory item; never part of the verdict.

    pass - linear/accelerating, same sign as the statistics, confidence not low (or no
    trend when the statistics see none); partial - trend_plus_step or low confidence;
    fail - step (likely artifact) or no_trend while the statistics are significant.
    """
    op = tr.ai_opinion
    if op is None:
        return None, False
    stats_sig = stat_item.status == "pass"
    stats_sign = _sign(tr.primary_slope_per_decade)
    cls = op.predicted_class
    if cls == "step" or (cls == "no_trend" and stats_sig):
        status: ItemStatus = "fail"
    elif cls == "trend_plus_step" or op.confidence == "low":
        status = "partial"
    elif cls in ("linear", "accelerating") and _sign(op.slope_per_decade) != stats_sign:
        status = "fail"
    else:
        status = "pass"
    ai_trend = cls in ("linear", "accelerating", "trend_plus_step")
    disagrees = ai_trend != stats_sig or (
        ai_trend and stats_sig and _sign(op.slope_per_decade) != stats_sign
    )
    item = EvidenceItem(
        key="ai_expert",
        status=status,
        score=SCORE[status],
        advisory=True,
        details=op.model_dump(mode="json"),
    )
    return item, disagrees


def _magnitude(tr: TrendResult) -> EvidenceItem:
    m = tr.magnitude
    if m is None:
        return _item("magnitude", "na", {})
    status: ItemStatus = {"strong": "pass", "moderate": "partial", "weak": "fail"}[m.snr_class]  # type: ignore[assignment]
    return _item("magnitude", status, m.model_dump(mode="json"))


def build_protocol(
    series: RegionalSeries,
    options: AnalysisOptions | None = None,
    *,
    witnesses: list[RegionalSeries] | None = None,
    indices: list[ClimateIndex] | None = None,
    changepoints: list[date] | None = None,
    sensor_events: list[SensorEvent] | None = None,
    split: SplitResult | None = None,
    zones: list[Zone] | None = None,
    ruleset: str = "verdict_rules_v1",
) -> EvidenceProtocol:
    """Full evidence protocol (section 6): statistics, magnitude, witnesses (difference
    series), robustness (triangle + jackknife), alibi (indices with block cross-validation),
    quality and the advisory ``ai_expert``; verdict and strength from the YAML ruleset (6.8).
    """
    opts = options or AnalysisOptions()
    rules = load_ruleset(ruleset)
    tr = analyze_series(series, opts)
    flags: list[QualityFlag] = list(tr.flags)
    codes = {f.code for f in flags}

    if codes & INADMISSIBLE_FLAGS or tr.test("ols_ar1") is None or tr.test("mk_ar1") is None:
        q = _item("quality", "fail", {"flags": [f.model_dump(mode="json") for f in flags]})
        caveats: list[str] = [
            c for c in ("short_record", "many_gaps", "low_stable_coverage") if c in codes
        ]
        return EvidenceProtocol(
            items=[q],
            verdict="inadmissible",
            strength=0,
            ruleset=rules.ruleset,
            direction="none",
            caveats=caveats,
        )

    p = prepare_series(series, opts)
    years, months = split_dates(p.dates)
    monthly = opts.season == "annual"
    if monthly:
        a_years, a_vals = annual_means(p.anom, years, months)
    else:
        a_years, a_vals = years, p.anom

    # Long memory (5.1 step 6): duplicate OLS on annual means.
    ofit = ols_ar1(p.t, p.anom)
    resid: FloatArray = (
        p.anom - (ofit.intercept + ofit.slope * p.t) if ofit else np.full(p.anom.shape, np.nan)
    )
    lm, lm_p = long_memory(resid) if monthly else (False, 1.0)
    if lm:
        flags.append(QualityFlag(code="long_memory", details={"ljung_box_p": lm_p}))
    ann = tr.test("ols_ar1_annual")
    p_ols_annual = ann.p_value if ann else None

    p_smk = seasonal_mk(p.values, months) if monthly else None
    stat_item, disagree = _statistics(tr, p_ols_annual, p_smk, opts.alpha)

    ref_sign = _sign(tr.primary_slope_per_decade)
    tri = trend_triangle(a_years, a_vals, ref_sign)
    robust_item = _item(
        "robustness",
        triangle_status(tri),
        tri.model_dump(mode="json") if tri else {},
    )

    wit = compare_witnesses(series, witnesses or [], opts.alpha)
    wit_status = witnesses_status(wit)
    wit_item = _item("witnesses", wit_status, wit.model_dump(mode="json") if wit else {})

    ali = alibi(p.t, p.anom, years, months, p.dates, indices or [], opts.alpha) if monthly else None
    ali_status = alibi_status(ali, opts.alpha)
    ali_item = _item("alibi", ali_status, ali.model_dump(mode="json") if ali else {})

    jk = tr.influence
    if jk is not None and jk.influential:
        flags.append(
            QualityFlag(
                code="influential_year",
                details={
                    "year": jk.significance_lost_year or jk.most_influential_year,
                    "max_rel_change": round(jk.max_rel_change, 3),
                },
            )
        )
    # Section 4.2: a sensor event inside the period is flagged and triggers a change-point
    # check even when change points were not requested.
    events_in = sensor_events_in_period(sensor_events or [], tr.period_used)
    if events_in:
        flags.append(
            QualityFlag(
                code="sensor_event_in_period",
                details={"events": [f"{e.code}@{e.date.isoformat()}" for e in events_in]},
            )
        )
    if changepoints is not None:
        cps = changepoints
    elif tr.changepoints or not events_in:
        cps = [c.at for c in tr.changepoints]
    else:
        monthly_cp = opts.season == "annual"
        cps = [
            c.at
            for c in detect_changepoints(
                p.t if monthly_cp else years.astype(np.float64),
                p.anom,
                step=1 / 12 if monthly_cp else 1.0,
                label_month=1 if monthly_cp else config.SEASON_LABEL_MONTH[opts.season],
                seed=opts.seed,
            )
        ]
    flags.extend(artifact_flags(cps, sensor_events or [], tr.period_used))
    quality_item = _item(
        "quality",
        quality_status(flags),
        {
            "flags": [f.model_dump(mode="json") for f in flags],
            "stable_fraction": series.stable_fraction,
            "n_eff": stat_item.details["n_eff"],
            "jackknife": jk.model_dump(mode="json") if jk else None,
            "changepoints": [d.isoformat() for d in cps],
            "split": split.model_dump(mode="json") if split else None,
            "zones": [z.model_dump(mode="json") for z in zones] if zones else [],
        },
    )

    items = [stat_item, _magnitude(tr), wit_item, robust_item, ali_item, quality_item]
    ai_item, ai_disagrees = _ai_expert(tr, stat_item)
    if ai_item is not None:
        items.append(ai_item)  # advisory: evaluate() ignores it
    verdict, strength = evaluate(items, rules)

    codes = {f.code for f in flags}
    case_caveats: list[str] = [
        c for c in ("many_gaps", "low_stable_coverage", "possible_artifact") if c in codes
    ]
    if disagree:
        case_caveats.append("methods_disagree")
    if wit_status == "fail" or (wit and any(pr.diverge for pr in wit.pairs)):
        case_caveats.append("witnesses_disagree")
    if robust_item.status in ("partial", "fail"):
        case_caveats.append("period_sensitive")
    if "influential_year" in codes:
        case_caveats.append("influential_year")
    case_caveats += alibi_caveats(ali, ali_status)
    if "long_memory" in codes:
        case_caveats.append("long_memory")
    if split is not None and split.split_flag:
        case_caveats.append("split_region")
    if ai_disagrees:
        case_caveats.append("ai_disagrees")

    direction: Direction = "none"
    if verdict in ("proven", "strong", "likely", "suspicious") and ref_sign:
        direction = "increasing" if ref_sign > 0 else "decreasing"
    return EvidenceProtocol(
        items=items,
        verdict=verdict,
        strength=strength,
        ruleset=rules.ruleset,
        direction=direction,
        caveats=case_caveats,
    )


__all__ = ["build_protocol"]
