"""Trend analysis of annual variables (section 7: indicators "are analysed by the same
protocol").

``analyze_series`` expects monthly data. Indicators have one value per year, so this path
runs the decision tests of the Stage 4 calibration directly on the annual values:
OLS + AR(1) n_eff (primary, ``ols_ar1_annual``), Mann-Kendall with the AR(1) rank correction
(confirmation), Sen's slope (rate), then magnitude, years to detect, jackknife, the
P-spline shape and the same ``decide`` as monthly series. The output is a regular
``TrendResult``, so the protocol, API and charts need no special case.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.evidence.verdict import decide
from earthtrend.analytics.models import (
    AnalysisOptions,
    Magnitude,
    SeriesMeta,
    SeriesPayload,
    TrendResult,
    TrendTest,
)
from earthtrend.analytics.preprocess.qc import is_constant, qc_flags
from earthtrend.analytics.trend.jackknife import jackknife
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.nonlinear import fit_spline
from earthtrend.analytics.trend.ols import ols_ar1
from earthtrend.analytics.trend.power import years_to_detect
from earthtrend.analytics.trend.sen import sen_slope

ANNUAL_LABEL_MONTH = 7  # annual values are dated 1 July on charts


def _snr_class(snr: float) -> Literal["weak", "moderate", "strong"]:
    if snr > config.SNR_STRONG:
        return "strong"
    if snr >= config.SNR_MODERATE:
        return "moderate"
    return "weak"


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def analyze_annual_series(
    years: Sequence[int] | np.ndarray,
    values: Sequence[float | None] | np.ndarray,
    meta: SeriesMeta,
    options: AnalysisOptions | None = None,
    stable_fraction: float = 1.0,
) -> TrendResult:
    """One value per year (gaps as None/NaN) -> ``TrendResult``.

    ``options.period`` and ``options.baseline`` apply; ``season``, ``seasonal_breakdown``,
    ``changepoints`` and ``bootstrap`` do not (an annual series has no months and is too
    short for BEAST to be informative).
    """
    opts = options or AnalysisOptions()
    yrs = np.asarray(years, dtype=np.int64)
    vals = np.array([np.nan if v is None else v for v in values], dtype=np.float64)
    if yrs.shape != vals.shape:
        raise ValueError("years and values must have the same length")
    if np.any(np.diff(yrs) <= 0):
        raise ValueError("years must be strictly increasing")
    if opts.period is not None:
        sel = (yrs >= opts.period[0]) & (yrs <= opts.period[1])
        yrs, vals = yrs[sel], vals[sel]

    if meta.transform == "log":
        with np.errstate(divide="ignore", invalid="ignore"):
            work = np.where(vals > 0, np.log(vals), np.nan)
    else:
        work = vals.copy()

    in_base = (
        (yrs >= opts.baseline[0]) & (yrs <= opts.baseline[1])
        if opts.baseline
        else np.ones(yrs.shape, dtype=bool)
    )
    ref = work[in_base & np.isfinite(work)]
    mu = float(ref.mean()) if ref.size else np.nan
    sd = float(ref.std(ddof=1)) if ref.size > 1 else np.nan
    anom = work - mu
    z = anom / sd if np.isfinite(sd) and sd > 0 else np.full(work.shape, np.nan)
    n_valid = int(np.isfinite(work).sum())
    flags = qc_flags(work, z, stable_fraction, float(n_valid), meta.min_years_for_trend)

    t = yrs.astype(np.float64) + (ANNUAL_LABEL_MONTH - 0.5) / 12.0
    tests: list[TrendTest] = []
    ols_t = mk_t = None
    fit = sen = None
    if n_valid and not is_constant(work):
        fit = ols_ar1(t, anom)
        if fit is not None:
            ols_t = TrendTest(
                method="ols_ar1_annual",
                slope_per_decade=fit.slope * 10,
                ci95=(fit.ci95[0] * 10, fit.ci95[1] * 10),
                p_value=fit.p_value,
                statistic=fit.t_stat if np.isfinite(fit.t_stat) else None,
                n=fit.n,
                n_eff=fit.n_eff,
            )
            tests.append(ols_t)
        mk = mk_ar1(anom)
        if mk is not None:
            mk_t = TrendTest(
                method="mk_ar1",
                slope_per_decade=None,
                ci95=None,
                p_value=mk.p_value,
                statistic=mk.z,
                n=mk.n,
            )
            tests.append(mk_t)
            sen = sen_slope(t, anom, mk.var_s, opts.alpha)
            if sen is not None:
                tests.append(
                    TrendTest(
                        method="sen",
                        slope_per_decade=sen.slope * 10,
                        ci95=(sen.ci95[0] * 10, sen.ci95[1] * 10),
                        p_value=None,
                        statistic=None,
                        n=sen.n,
                    )
                )

    magnitude = None
    ytd = ytd_rem = None
    if sen is not None:
        sigma = float(np.nanstd(anom, ddof=1))
        spd = sen.slope * 10
        snr = abs(spd) / sigma if sigma > 0 else 0.0
        pct: float | None = None
        if meta.transform == "log":
            pct = (float(np.exp(spd)) - 1.0) * 100.0
        elif meta.ratio_scale:
            m = float(np.nanmean(vals))
            pct = spd / abs(m) * 100.0 if m else None
        magnitude = Magnitude(
            slope_per_decade=spd,
            percent_per_decade=pct,
            sigma_anom=sigma,
            snr=snr,
            snr_class=_snr_class(snr),
        )
        if fit is not None:
            ytd = years_to_detect(sen.slope, fit.resid_std, fit.r1)
            if ytd is not None:
                ytd_rem = max(0.0, ytd - n_valid)

    # The annual OLS is both the primary and the only OLS test here.
    verdict = decide(
        flags=flags, ols=ols_t, mk=mk_t, magnitude=magnitude, alpha=opts.alpha, ols_annual=ols_t
    )

    nonlinear = influence = None
    if sen is not None:
        influence = jackknife(yrs, anom, opts.alpha)
        if opts.nonlinear:
            nonlinear = fit_spline(yrs, anom)

    dates = [date(int(y), ANNUAL_LABEL_MONTH, 1) for y in yrs]
    trend: list[float] = []
    lo: list[float] = []
    hi: list[float] = []
    if sen is not None:
        line = sen.intercept + sen.slope * t
        t_mid = float(np.median(t[np.isfinite(anom)]))
        y_mid = sen.intercept + sen.slope * t_mid
        a = y_mid + sen.ci95[0] * (t - t_mid)
        b = y_mid + sen.ci95[1] * (t - t_mid)
        trend, lo, hi = line.tolist(), np.minimum(a, b).tolist(), np.maximum(a, b).tolist()

    valid_dates = [d for d, v in zip(dates, anom, strict=True) if np.isfinite(v)]
    facts: dict[str, object] = {
        "variable_id": meta.variable_id,
        "region_id": meta.region_id,
        "units": meta.units,
        "years_of_data": n_valid,
        "period_start": valid_dates[0].isoformat() if valid_dates else None,
        "period_end": valid_dates[-1].isoformat() if valid_dates else None,
        "verdict": verdict.code,
        "direction": verdict.direction,
        "frequency": "annual",
    }
    for tt in tests:
        facts[f"p_{tt.method}"] = _r(tt.p_value, 4)
    if sen is not None:
        facts["slope_per_decade"] = _r(sen.slope * 10)
        facts["ci95_low"] = _r(sen.ci95[0] * 10)
        facts["ci95_high"] = _r(sen.ci95[1] * 10)
    if magnitude is not None:
        facts["snr"] = _r(magnitude.snr, 2)
        facts["snr_class"] = magnitude.snr_class
        facts["percent_per_decade"] = _r(magnitude.percent_per_decade, 2)
    facts["years_to_detect"] = _r(ytd, 1)
    facts["years_to_detect_remaining"] = _r(ytd_rem, 1)

    def to_list(x: np.ndarray) -> list[float | None]:
        return [float(v) if np.isfinite(v) else None for v in x]

    return TrendResult(
        meta=meta,
        options=opts.model_copy(update={"seasonal_breakdown": False}),
        period_used=(valid_dates[0], valid_dates[-1]) if valid_dates else None,
        n_used=len(valid_dates),
        years_of_data=float(n_valid),
        tests=tests,
        primary_slope_per_decade=sen.slope * 10 if sen else None,
        primary_ci95=(sen.ci95[0] * 10, sen.ci95[1] * 10) if sen else None,
        direction=verdict.direction,
        magnitude=magnitude,
        years_to_detect=ytd,
        years_to_detect_remaining=ytd_rem,
        flags=flags,
        series_out=SeriesPayload(
            dates=dates,
            values=to_list(vals),
            anomalies=to_list(anom),
            trend=trend,
            ci_low=lo,
            ci_high=hi,
        ),
        verdict=verdict,
        nonlinear=nonlinear,
        influence=influence,
        summary_text_facts=facts,
    )
