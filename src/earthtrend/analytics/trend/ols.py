"""OLS trend with the AR(1) effective-sample-size correction (section 5.1, Santer et al. 2000)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from earthtrend.analytics import config
from earthtrend.analytics.preprocess.aggregate import FloatArray


@dataclass(frozen=True)
class OlsFit:
    """OLS trend fit with AR(1)-corrected inference.

    n_eff = n (1 - r1) / (1 + r1); SE = sqrt(SSE / (n_eff - 2) / Sxx); Santer et al. (2000).
    """

    slope: float  # units per year
    intercept: float
    se: float
    ci95: tuple[float, float]
    p_value: float
    t_stat: float
    n: int
    n_eff: float
    r1: float  # lag-1 autocorrelation of residuals
    resid_std: float
    p_value_naive: float  # without the n_eff correction (documentation / tests only)


def lag1_autocorrelation(resid: FloatArray) -> float:
    """Lag-1 autocorrelation over consecutive pairs where both values exist."""
    a, b = resid[:-1], resid[1:]
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return 0.0
    a, b = a[ok], b[ok]
    mean = np.nanmean(resid)
    var = np.nanmean((resid - mean) ** 2)
    if var == 0:
        return 0.0
    return float(np.mean((a - mean) * (b - mean)) / var)


def ols_ar1(t: FloatArray, y: FloatArray) -> OlsFit | None:
    """Fit ``y = a + b t``; ``t`` in decimal years, gaps as NaN in ``y``."""
    ok = np.isfinite(y) & np.isfinite(t)
    n = int(ok.sum())
    if n < 3:
        return None
    tv, yv = t[ok], y[ok]
    tbar = tv.mean()
    sxx = float(np.sum((tv - tbar) ** 2))
    if sxx == 0:
        return None
    slope = float(np.sum((tv - tbar) * (yv - yv.mean())) / sxx)
    intercept = float(yv.mean() - slope * tbar)

    resid_full = np.full(y.shape, np.nan)
    resid_full[ok] = yv - (intercept + slope * tv)
    resid = resid_full[ok]
    r1 = lag1_autocorrelation(resid_full)
    n_eff = n * (1 - r1) / (1 + r1) if r1 > 0 else float(n)
    n_eff = float(np.clip(n_eff, config.N_EFF_MIN, n))

    sse = float(np.sum(resid**2))
    dof = n_eff - 2.0
    se = float(np.sqrt(sse / dof / sxx))
    dof_naive = n - 2.0
    se_naive = float(np.sqrt(sse / dof_naive / sxx)) if dof_naive > 0 else np.inf

    def _p(se_: float, dof_: float) -> tuple[float, float]:
        if se_ == 0:
            return (0.0 if slope != 0 else 1.0), np.inf
        tt = slope / se_
        return float(2 * stats.t.sf(abs(tt), dof_)), float(tt)

    p, t_stat = _p(se, dof)
    p_naive, _ = _p(se_naive, dof_naive) if dof_naive > 0 else (1.0, 0.0)
    half = float(stats.t.ppf(0.975, dof)) * se
    return OlsFit(
        slope=slope,
        intercept=intercept,
        se=se,
        ci95=(slope - half, slope + half),
        p_value=p,
        t_stat=t_stat,
        n=n,
        n_eff=n_eff,
        r1=r1,
        resid_std=float(np.std(resid, ddof=2)) if n > 2 else 0.0,
        p_value_naive=p_naive,
    )
