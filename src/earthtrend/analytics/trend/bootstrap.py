"""Moving-block bootstrap of OLS residuals (section 5.4).

L = max(3, round(n^(1/3) (1 + r1) / (1 - r1))); percentile CI of the OLS slope.
Gaps are dropped (the residual series is treated as contiguous).
"""

from __future__ import annotations

import numpy as np

from earthtrend.analytics.models import BootstrapResult
from earthtrend.analytics.preprocess.aggregate import FloatArray
from earthtrend.analytics.trend.ols import lag1_autocorrelation


def block_length(n: int, r1: float) -> int:
    r1 = min(max(r1, 0.0), 0.95)
    return max(3, round(n ** (1 / 3) * (1 + r1) / (1 - r1)))


def block_bootstrap(
    t: FloatArray, y: FloatArray, n_boot: int = 2000, seed: int = 42, alpha: float = 0.05
) -> BootstrapResult | None:
    ok = np.isfinite(t) & np.isfinite(y)
    tv, yv = t[ok], y[ok]
    n = tv.size
    if n < 10:
        return None
    dt = tv - tv.mean()
    sxx = float(dt @ dt)
    slope = float(dt @ (yv - yv.mean()) / sxx)
    fit = yv.mean() + slope * dt
    resid = yv - fit
    r1 = lag1_autocorrelation(resid)
    ell = min(block_length(n, r1), n)

    rng = np.random.default_rng(seed)
    n_blocks = -(-n // ell)
    starts = rng.integers(0, n - ell + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(ell)[None, None, :]).reshape(n_boot, -1)[:, :n]
    y_star = fit[None, :] + resid[idx]
    slopes = (y_star - y_star.mean(axis=1, keepdims=True)) @ dt / sxx
    lo, hi = np.quantile(slopes, [alpha / 2, 1 - alpha / 2])
    return BootstrapResult(
        slope_ci95_per_decade=(float(lo) * 10, float(hi) * 10),
        block_length=ell,
        n_boot=n_boot,
        seed=seed,
    )
