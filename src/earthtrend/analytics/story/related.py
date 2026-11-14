"""Related variables for a story (docs/PLAN_ANALYTICS.md section 10.2).

For every candidate series in the same region whose concept is within 2 edges of the main
concept in the process graph:
* its trend in the same season and period (``analyze_series``, light options);
* Pearson r of **detrended** anomalies at the route's lag (detrending is mandatory: any two
  trends correlate spuriously). Monthly anomalies for ``annual``, seasonal means otherwise
  (the lag is then rounded to whole years);
* p of r with the AR(1) effective sample size n_eff = n (1 - r1a r1b) / (1 + r1a r1b)
  (Bretherton et al., 1999), t-test with n_eff - 2 degrees of freedom;
* partial r controlling for the detrended control concept (temperature) at lag 0 of the
  main series, n_eff - 3 degrees of freedom;
* consistency of the signs of r and of the trends with the route's expected sign.

One dataset per concept: the first candidate given for it is used.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series, prepare_series, to_monthly
from earthtrend.analytics.models import (
    AnalysisOptions,
    Direction,
    RegionalSeries,
    TrendResult,
    Verdict,
)
from earthtrend.analytics.preprocess.aggregate import FloatArray
from earthtrend.analytics.story.models import Consistency, ProcessGraph, RelatedVariable
from earthtrend.analytics.story.process_graph import default_process_graph
from earthtrend.analytics.trend.ols import lag1_autocorrelation

MIN_OVERLAP_MONTHS = 36
MIN_OVERLAP_YEARS = 10


@dataclass(frozen=True)
class Detrended:
    """Detrended anomalies keyed by month index (year * 12 + month - 1)."""

    values: dict[int, float]
    r1: float


def light_options(opts: AnalysisOptions, period: tuple[int, int] | None) -> AnalysisOptions:
    return opts.model_copy(
        update={
            "period": period,
            "nonlinear": False,
            "seasonal_breakdown": False,
            "changepoints": False,
            "bootstrap": False,
            "expert": False,
        }
    )


def detrended_anomalies(series: RegionalSeries, opts: AnalysisOptions) -> Detrended:
    p = prepare_series(to_monthly(series), opts)
    ok = np.isfinite(p.anom)
    resid: FloatArray = np.full(p.anom.shape, np.nan)
    if ok.sum() >= 3:
        coef = np.polyfit(p.t[ok], p.anom[ok], 1)
        resid[ok] = p.anom[ok] - np.polyval(coef, p.t[ok])
    values = {
        d.year * 12 + d.month - 1: float(v)
        for d, v in zip(p.dates, resid, strict=True)
        if np.isfinite(v)
    }
    return Detrended(values, lag1_autocorrelation(resid))


def _p_from_r(r: float, dof: float) -> float:
    if dof <= 0 or not np.isfinite(r):
        return float("nan")
    if abs(r) >= 1.0:
        return 0.0
    t = r * math.sqrt(dof / (1.0 - r * r))
    return float(2 * stats.t.sf(abs(t), dof))


def lagged_correlation(
    main: Detrended,
    other: Detrended,
    lag_months: int,
    control: Detrended | None = None,
    min_overlap: int = MIN_OVERLAP_MONTHS,
) -> tuple[int, float | None, float | None, float | None, float | None, float | None]:
    """corr(main(t), other(t + lag)), optionally partial on control(t).

    Returns (n, r, p, n_eff, partial r, partial p).
    """
    keys = [
        m
        for m in main.values
        if m + lag_months in other.values and (control is None or m in control.values)
    ]
    n = len(keys)
    if n < min_overlap:
        return n, None, None, None, None, None
    a = np.array([main.values[m] for m in keys])
    b = np.array([other.values[m + lag_months] for m in keys])
    if a.std() == 0 or b.std() == 0:
        return n, None, None, None, None, None
    r = float(np.corrcoef(a, b)[0, 1])
    rr = main.r1 * other.r1
    n_eff = float(np.clip(n * (1 - rr) / (1 + rr), 3.0, n))
    p = _p_from_r(r, n_eff - 2)
    pr = pp = None
    if control is not None:
        c = np.array([control.values[m] for m in keys])
        if c.std() > 0:
            x = np.column_stack([np.ones(n), c])
            ra = a - x @ np.linalg.lstsq(x, a, rcond=None)[0]
            rb = b - x @ np.linalg.lstsq(x, b, rcond=None)[0]
            if ra.std() > 0 and rb.std() > 0:
                pr = float(np.corrcoef(ra, rb)[0, 1])
                pp = _p_from_r(pr, n_eff - 3)
    return n, r, p, n_eff, pr, pp


def verdict_strength(v: Verdict) -> float:
    """Strength in 0..1. The quick ``verdict_rules_v0`` tops out at the sum of its weights."""
    top = sum(config.STRENGTH_WEIGHTS.values()) if v.ruleset == "verdict_rules_v0" else 100
    return float(min(1.0, v.strength / top))


def _sign(direction: Direction) -> int:
    return 1 if direction == "increasing" else -1 if direction == "decreasing" else 0


def _corr_consistency(r: float | None, p: float | None, expected: int, alpha: float) -> Consistency:
    if r is None or p is None or not np.isfinite(p) or p >= alpha:
        return "unclear"
    return "consistent" if np.sign(r) == expected else "inconsistent"


def _trend_consistency(main: Direction, other: Direction, expected: int) -> Consistency:
    a, b = _sign(main), _sign(other)
    if a == 0 or b == 0:
        return "unclear"
    return "consistent" if a * expected == b else "inconsistent"


def related_variables(
    main: RegionalSeries,
    candidates: Sequence[RegionalSeries],
    graph: ProcessGraph | None = None,
    options: AnalysisOptions | None = None,
    *,
    main_result: TrendResult | None = None,
    main_direction: Direction | None = None,
    max_depth: int = 2,
) -> list[RelatedVariable]:
    """Related variables of ``main`` among ``candidates`` (any region; others are skipped)."""
    g = graph or default_process_graph()
    opts = options or AnalysisOptions()
    tr = main_result or analyze_series(main, light_options(opts, opts.period))
    period = (tr.period_used[0].year, tr.period_used[1].year) if tr.period_used else opts.period
    lopts = light_options(opts, period)
    direction = main_direction or tr.verdict.direction
    monthly = opts.season == "annual"
    min_overlap = MIN_OVERLAP_MONTHS if monthly else MIN_OVERLAP_YEARS

    meta = main.meta
    routes = {r.concept_id: r for r in g.neighbors(meta.concept_id, max_depth)}
    same_region = [c for c in candidates if c.meta.region_id == meta.region_id]
    control_series = None
    if meta.concept_id != g.control_concept:
        control_series = next(
            (c for c in same_region if c.meta.concept_id == g.control_concept), None
        )
    main_d = detrended_anomalies(main, lopts)
    control_d = detrended_anomalies(control_series, lopts) if control_series else None

    out: list[RelatedVariable] = []
    used: set[str] = set()
    for cand in same_region:
        concept = cand.meta.concept_id
        route = routes.get(concept)
        if route is None or concept in used:
            continue
        used.add(concept)
        ctr = analyze_series(cand, lopts)
        mk = ctr.test("mk_ar1")
        lag = route.lag_months if monthly else 12 * round(route.lag_months / 12)
        use_control = control_d if concept != g.control_concept else None
        n, r, p, n_eff, pr, pp = lagged_correlation(
            main_d, detrended_anomalies(cand, lopts), lag, use_control, min_overlap
        )
        out.append(
            RelatedVariable(
                variable_id=cand.meta.variable_id,
                concept_id=concept,
                dataset_id=cand.meta.dataset_id,
                route=route,
                season=opts.season,
                slope_per_decade=ctr.primary_slope_per_decade,
                ci95=ctr.primary_ci95,
                p_mk=mk.p_value if mk else None,
                direction=ctr.verdict.direction,
                verdict=ctr.verdict.code,
                strength=verdict_strength(ctr.verdict),
                lag_used_months=lag,
                n_overlap=n,
                corr=r,
                corr_p=p,
                n_eff=n_eff,
                partial_corr=pr,
                partial_p=pp,
                controlled_for=g.control_concept if use_control is not None else None,
                corr_consistency=_corr_consistency(r, p, route.expected_sign, opts.alpha),
                trend_consistency=_trend_consistency(
                    direction, ctr.verdict.direction, route.expected_sign
                ),
            )
        )
    out.sort(key=lambda v: (v.route.depth, -abs(v.corr or 0.0), v.variable_id))
    return out


__all__ = ["detrended_anomalies", "lagged_correlation", "related_variables"]
