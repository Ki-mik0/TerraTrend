"""``analyze_series``: one regional series -> ``TrendResult`` with a verdict.

Pipeline: transform -> period -> (season) -> anomalies -> QC -> OLS-AR(1), MK-HR, Sen
-> magnitude, years to detect -> verdict -> chart payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.evidence.verdict import decide
from earthtrend.analytics.models import (
    AiOpinion,
    AnalysisOptions,
    Changepoint,
    Magnitude,
    MonthTrend,
    QualityFlag,
    RegionalSeries,
    SeriesMeta,
    SeriesPayload,
    TrendResult,
    TrendTest,
    Verdict,
)
from earthtrend.analytics.preprocess.aggregate import (
    FloatArray,
    annual_means,
    daily_to_monthly,
    decimal_year,
    seasonal_means,
    split_dates,
)
from earthtrend.analytics.preprocess.anomalies import anomalies, standardized_anomalies
from earthtrend.analytics.preprocess.climatology import monthly_climatology
from earthtrend.analytics.preprocess.decompose import stl_decompose
from earthtrend.analytics.preprocess.qc import is_constant, qc_flags
from earthtrend.analytics.trend.bootstrap import block_bootstrap
from earthtrend.analytics.trend.changepoint import detect_changepoints
from earthtrend.analytics.trend.glsar import glsar_trend
from earthtrend.analytics.trend.jackknife import jackknife
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.monthly import monthly_trends
from earthtrend.analytics.trend.nonlinear import fit_spline
from earthtrend.analytics.trend.ols import ols_ar1
from earthtrend.analytics.trend.power import years_to_detect
from earthtrend.analytics.trend.sen import sen_slope


@dataclass
class PreparedSeries:
    t: FloatArray  # decimal years
    anom: FloatArray  # anomalies in analysis units
    z: FloatArray  # standardized anomalies (outlier check)
    values: FloatArray  # analysis units (after transform), for QC
    raw: FloatArray  # original units, for the chart
    dates: list[date]
    years_of_data: float


def _snr_class(snr: float) -> Literal["weak", "moderate", "strong"]:
    if snr > config.SNR_STRONG:
        return "strong"
    if snr >= config.SNR_MODERATE:
        return "moderate"
    return "weak"


def _to_list(x: FloatArray) -> list[float | None]:
    return [float(v) if np.isfinite(v) else None for v in x]


def prepare_series(series: RegionalSeries, opts: AnalysisOptions) -> PreparedSeries:
    """Transform (log), period and season selection, climatology and anomalies (section 4.3).

    Annual season: monthly anomalies x - clim_mean[month] (baseline = ``opts.baseline`` or the
    whole period). Other seasons: seasonal means, anomalies against their baseline mean.
    """
    years, months = split_dates(series.dates)
    raw = np.array([np.nan if v is None else v for v in series.values], dtype=np.float64)

    # Transform: log variables are analysed on log(x) and reported as % per decade.
    values = raw.copy()
    if series.meta.transform == "log":
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.where(raw > 0, np.log(raw), np.nan)

    if opts.period is not None:
        sel = (years >= opts.period[0]) & (years <= opts.period[1])
        if opts.season == "DJF":  # DJF of the first year needs the previous December
            sel |= (years == opts.period[0] - 1) & (months == 12)
        years, months, values, raw = years[sel], months[sel], values[sel], raw[sel]

    if years.size == 0:
        empty = np.empty(0)
        return PreparedSeries(empty, empty, empty, empty, empty, [], 0.0)

    if opts.season == "annual":
        clim_mean, clim_std = monthly_climatology(values, years, months, opts.baseline)
        return PreparedSeries(
            t=decimal_year(years, months),
            anom=anomalies(values, months, clim_mean),
            z=standardized_anomalies(values, months, clim_mean, clim_std),
            values=values,
            raw=raw,
            dates=[date(int(y), int(m), 1) for y, m in zip(years, months, strict=True)],
            years_of_data=float(np.isfinite(values).sum()) / 12.0,
        )

    sy, sv = seasonal_means(values, years, months, opts.season)
    if opts.period is not None:
        keep = (sy >= opts.period[0]) & (sy <= opts.period[1])
        sy, sv = sy[keep], sv[keep]
    in_base = (
        (sy >= opts.baseline[0]) & (sy <= opts.baseline[1])
        if opts.baseline
        else np.ones(sy.shape, dtype=bool)
    )
    ref = sv[in_base & np.isfinite(sv)]
    mu = float(ref.mean()) if ref.size else np.nan
    sd = float(ref.std(ddof=1)) if ref.size > 1 else np.nan
    anom = sv - mu
    z = anom / sd if np.isfinite(sd) and sd > 0 else np.full(sv.shape, np.nan)
    label = config.SEASON_LABEL_MONTH[opts.season]
    return PreparedSeries(
        t=sy.astype(np.float64) + (label - 0.5) / 12.0,
        anom=anom,
        z=z,
        values=sv,
        raw=np.exp(sv) if series.meta.transform == "log" else sv,
        dates=[date(int(y), label, 1) for y in sy],
        years_of_data=float(np.isfinite(sv).sum()),
    )


def _ai_opinion(
    opts: AnalysisOptions, p: PreparedSeries, sen: Any, verdict: Verdict
) -> AiOpinion | None:
    """M1 TrendNet opinion (advisory, section 6.7); None without an active model."""
    if not opts.ai_opinion or sen is None or opts.season != "annual":
        return None
    from earthtrend.analytics.ml.trendnet import ai_opinion

    _, months = split_dates(p.dates)
    return ai_opinion(
        p.anom,
        months,
        stats_significant=verdict.code == "strong",
        stats_sign=int(np.sign(sen.slope)),
    )


def to_monthly(series: RegionalSeries) -> RegionalSeries:
    """Daily series -> monthly with the passport's aggregation rule (section 4.1)."""
    if series.meta.frequency != "daily":
        return series
    dates, values = daily_to_monthly(series.dates, series.values, series.meta.aggregation)
    return RegionalSeries(
        meta=series.meta.model_copy(update={"frequency": "monthly"}),
        dates=dates,
        values=values,
        stable_fraction=series.stable_fraction,
    )


def _facts(
    meta: SeriesMeta,
    years: float,
    tests: list[TrendTest],
    sen: Any,
    magnitude: Magnitude | None,
    ytd: float | None,
    ytd_rem: float | None,
    valid_dates: list[date],
    verdict: Verdict,
) -> dict[str, Any]:
    """Rounded numbers that texts may quote (and nothing else)."""

    def r(x: float | None, nd: int = 3) -> float | None:
        return None if x is None else round(float(x), nd)

    facts: dict[str, Any] = {
        "variable_id": meta.variable_id,
        "region_id": meta.region_id,
        "units": meta.units,
        "years_of_data": r(years, 1),
        "period_start": valid_dates[0].isoformat() if valid_dates else None,
        "period_end": valid_dates[-1].isoformat() if valid_dates else None,
        "verdict": verdict.code,
        "direction": verdict.direction,
    }
    for t in tests:
        facts[f"p_{t.method}"] = r(t.p_value, 4)
    if sen is not None:
        facts["slope_per_decade"] = r(sen.slope * 10)
        facts["ci95_low"] = r(sen.ci95[0] * 10)
        facts["ci95_high"] = r(sen.ci95[1] * 10)
    if magnitude is not None:
        facts["percent_per_decade"] = r(magnitude.percent_per_decade, 2)
        facts["snr"] = r(magnitude.snr, 2)
        facts["snr_class"] = magnitude.snr_class
    facts["years_to_detect"] = r(ytd, 1)
    facts["years_to_detect_remaining"] = r(ytd_rem, 1)
    return facts


def analyze_series(series: RegionalSeries, options: AnalysisOptions | None = None) -> TrendResult:
    """One regional series -> ``TrendResult`` (sections 4-5, Stage 4 decision rule).

    OLS + AR(1) n_eff (also on annual means), Mann-Kendall with the AR(1) rank correction,
    Sen's slope with the Gilbert (1987) CI, SNR, Weatherhead (1998) years to detect, QC flags
    and the verdict; plus the optional depth items of stage A4.
    """
    opts = options or AnalysisOptions()
    series = to_monthly(series)
    meta = series.meta
    p = prepare_series(series, opts)

    flags: list[QualityFlag] = qc_flags(
        p.values, p.z, series.stable_fraction, p.years_of_data, meta.min_years_for_trend
    )

    # Tests.
    tests: list[TrendTest] = []
    ols_t = mk_t = ols_ann_t = None
    ofit = sen = None
    if p.anom.size and not is_constant(p.values):
        if opts.season == "annual":
            # Calibration (Stage 4): monthly AR(1) corrections under-cover long memory
            # (11-12% false alarms on long-memory surrogates). The same OLS on annual
            # means stays at ~5% and is required as well.
            y_, m_ = split_dates(p.dates)
            ay_, av_ = annual_means(p.anom, y_, m_)
            afit = ols_ar1(ay_.astype(np.float64), av_)
            if afit is not None:
                ols_ann_t = TrendTest(
                    method="ols_ar1_annual",
                    slope_per_decade=afit.slope * 10,
                    ci95=(afit.ci95[0] * 10, afit.ci95[1] * 10),
                    p_value=afit.p_value,
                    statistic=afit.t_stat if np.isfinite(afit.t_stat) else None,
                    n=afit.n,
                    n_eff=afit.n_eff,
                )
                tests.append(ols_ann_t)
        ofit = ols_ar1(p.t, p.anom)
        if ofit is not None:
            ols_t = TrendTest(
                method="ols_ar1",
                slope_per_decade=ofit.slope * 10,
                ci95=(ofit.ci95[0] * 10, ofit.ci95[1] * 10),
                p_value=ofit.p_value,
                statistic=ofit.t_stat if np.isfinite(ofit.t_stat) else None,
                n=ofit.n,
                n_eff=ofit.n_eff,
            )
            tests.append(ols_t)
            if ofit.n_eff < config.N_EFF_UNRELIABLE:
                flags.append(QualityFlag(code="low_n_eff", details={"n_eff": round(ofit.n_eff, 2)}))
        mk = mk_ar1(p.anom)
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
            sen = sen_slope(p.t, p.anom, mk.var_s, opts.alpha)
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

    # Magnitude (section 6.1) and years to detect (section 5.7).
    magnitude = None
    ytd = ytd_rem = None
    if sen is not None:
        sigma_anom = float(np.nanstd(p.anom, ddof=1))
        spd = sen.slope * 10
        snr = abs(spd) / sigma_anom if sigma_anom > 0 else 0.0
        pct: float | None = None
        if meta.transform == "log":
            pct = (float(np.exp(spd)) - 1.0) * 100.0
        elif meta.ratio_scale:
            mean_raw = float(np.nanmean(p.raw))
            pct = spd / abs(mean_raw) * 100.0 if mean_raw else None
        magnitude = Magnitude(
            slope_per_decade=spd,
            percent_per_decade=pct,
            sigma_anom=sigma_anom,
            snr=snr,
            snr_class=_snr_class(snr),
        )
        if ofit is not None:
            ytd = years_to_detect(sen.slope, ofit.resid_std, ofit.r1)
            if ytd is not None:
                ytd_rem = max(0.0, ytd - p.years_of_data)

    verdict = decide(
        flags=flags, ols=ols_t, mk=mk_t, magnitude=magnitude, alpha=opts.alpha, ols_annual=ols_ann_t
    )

    # Depth (stage A4) and influence: only when the core tests ran.
    nonlinear = influence = boot = stl = None
    changepoints: list[Changepoint] = []
    breakdown: list[MonthTrend] = []
    if sen is not None:
        years, months = split_dates(p.dates)
        monthly = opts.season == "annual"
        a_years, a_vals = annual_means(p.anom, years, months) if monthly else (years, p.anom)
        influence = jackknife(a_years, a_vals, opts.alpha)
        if opts.nonlinear:
            nonlinear = fit_spline(a_years, a_vals)
        if opts.seasonal_breakdown and monthly:
            breakdown = monthly_trends(p.values, years, months, opts.alpha)
        if opts.changepoints:
            label = 1 if monthly else config.SEASON_LABEL_MONTH[opts.season]
            changepoints = detect_changepoints(
                p.t if monthly else years.astype(np.float64),
                p.anom,
                step=1 / 12 if monthly else 1.0,
                label_month=label,
                seed=opts.seed,
            )
        if opts.bootstrap or opts.expert:
            boot = block_bootstrap(p.t, p.anom, opts.n_boot, opts.seed, opts.alpha)
        if opts.expert:
            g = glsar_trend(p.t, p.anom)
            if g is not None:
                tests.append(
                    TrendTest(
                        method="glsar",
                        slope_per_decade=g.slope * 10,
                        ci95=(g.ci95[0] * 10, g.ci95[1] * 10),
                        p_value=g.p_value,
                        statistic=g.t_stat,
                        n=g.n,
                    )
                )
            if monthly:
                stl = stl_decompose(p.dates, p.values)

    # Chart payload: Sen line and slope-uncertainty band pivoting at the median time.
    trend: list[float] = []
    ci_low: list[float] = []
    ci_high: list[float] = []
    if sen is not None:
        line = sen.intercept + sen.slope * p.t
        t_mid = float(np.median(p.t[np.isfinite(p.anom)]))
        y_mid = sen.intercept + sen.slope * t_mid
        a = y_mid + sen.ci95[0] * (p.t - t_mid)
        b = y_mid + sen.ci95[1] * (p.t - t_mid)
        trend = line.tolist()
        ci_low = np.minimum(a, b).tolist()
        ci_high = np.maximum(a, b).tolist()

    valid_dates = [d for d, v in zip(p.dates, p.anom, strict=True) if np.isfinite(v)]
    return TrendResult(
        meta=meta,
        options=opts,
        period_used=(valid_dates[0], valid_dates[-1]) if valid_dates else None,
        n_used=len(valid_dates),
        years_of_data=p.years_of_data,
        tests=tests,
        primary_slope_per_decade=sen.slope * 10 if sen else None,
        primary_ci95=(sen.ci95[0] * 10, sen.ci95[1] * 10) if sen else None,
        direction=verdict.direction,
        magnitude=magnitude,
        years_to_detect=ytd,
        years_to_detect_remaining=ytd_rem,
        flags=flags,
        series_out=SeriesPayload(
            dates=p.dates,
            values=_to_list(p.raw),
            anomalies=_to_list(p.anom),
            trend=trend,
            ci_low=ci_low,
            ci_high=ci_high,
        ),
        verdict=verdict,
        nonlinear=nonlinear,
        changepoints=changepoints,
        seasonal_breakdown=breakdown,
        influence=influence,
        bootstrap=boot,
        stl=stl,
        ai_opinion=_ai_opinion(opts, p, sen, verdict),
        summary_text_facts=_facts(
            meta, p.years_of_data, tests, sen, magnitude, ytd, ytd_rem, valid_dates, verdict
        ),
    )
