"""Non-linearity (section 5.5): penalized cubic spline (P-spline) on annual means.

Eilers & Marx P-spline: cubic B-spline basis on equally spaced knots, second-difference
penalty, smoothing chosen by generalized cross-validation. Bands from the Bayesian
covariance sigma^2 (B'B + lambda D'D)^-1.

Acceleration (both conditions): AIC of the curve better than the straight line by >= 4,
and the mean derivative in the last third differs from the first third with |z| > 1.96
(in the direction of the overall trend: + accelerating, - decelerating).
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import BSpline

from earthtrend.analytics.models import NonlinearResult
from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray

DEGREE = 3
LAMBDAS = 10.0 ** np.linspace(-4, 6, 41)
DELTA_AIC = 4.0
Z_CRIT = 1.96
MIN_YEARS = 10


def _basis(x: FloatArray, lo: float, hi: float, n_seg: int) -> tuple[FloatArray, FloatArray]:
    dx = (hi - lo) / n_seg
    knots = lo + dx * np.arange(-DEGREE, n_seg + DEGREE + 1)
    nb = n_seg + DEGREE
    spl = BSpline(knots, np.eye(nb), DEGREE, extrapolate=False)
    b = np.nan_to_num(spl(x))
    db = np.nan_to_num(spl.derivative()(x))
    return b, db


def fit_spline(years: IntArray, annual: FloatArray) -> NonlinearResult | None:
    """P-spline (Eilers & Marx, 1996) on annual means: cubic B-splines, 2nd-difference penalty,
    lambda by GCV, Bayesian bands; shape from AIC vs the line and the derivative change.
    """
    ok = np.isfinite(annual)
    n = int(ok.sum())
    if n < MIN_YEARS:
        return None
    x = years[ok].astype(np.float64)
    y = annual[ok]
    lo, hi = float(x.min()), float(x.max())
    n_seg = max(4, min(20, n // 4))
    b, _ = _basis(x, lo, hi, n_seg)
    nb = b.shape[1]
    d = np.diff(np.eye(nb), n=2, axis=0)
    btb, bty, pen = b.T @ b, b.T @ y, d.T @ d

    best: tuple[float, float, FloatArray, FloatArray, float] | None = None
    for lam in LAMBDAS:
        a = btb + lam * pen
        a_inv = np.linalg.inv(a)
        beta = a_inv @ bty
        edf = float(np.trace(a_inv @ btb))
        rss = float(np.sum((y - b @ beta) ** 2))
        if n - edf <= 1:
            continue
        gcv = n * rss / (n - edf) ** 2
        if best is None or gcv < best[0]:
            best = (gcv, float(lam), beta, a_inv, edf)
    if best is None:
        return None
    _, lam, beta, a_inv, edf = best
    rss = float(np.sum((y - b @ beta) ** 2))
    sigma2 = rss / (n - edf)
    cov = sigma2 * a_inv

    # Straight line for comparison.
    xc = x - x.mean()
    slope = float(xc @ (y - y.mean()) / (xc @ xc))
    rss_lin = float(np.sum((y - y.mean() - slope * xc) ** 2))
    aic_lin = n * np.log(rss_lin / n) + 2 * 2
    aic_spl = n * np.log(rss / n) + 2 * edf

    grid = np.arange(int(lo), int(hi) + 1, dtype=np.float64)
    bg, dbg = _basis(grid, lo, hi, n_seg)
    curve = bg @ beta
    deriv = dbg @ beta
    c_sd = np.sqrt(np.einsum("ij,jk,ik->i", bg, cov, bg))
    d_sd = np.sqrt(np.einsum("ij,jk,ik->i", dbg, cov, dbg))

    third = max(1, grid.size // 3)
    w = dbg[-third:].mean(axis=0) - dbg[:third].mean(axis=0)
    diff = float(w @ beta)
    sd = float(np.sqrt(w @ cov @ w))
    direction = 1.0 if slope >= 0 else -1.0
    z = direction * diff / sd if sd > 0 else 0.0
    delta = float(aic_lin - aic_spl)
    if delta >= DELTA_AIC and z > Z_CRIT:
        shape = "accelerating"
    elif delta >= DELTA_AIC and z < -Z_CRIT:
        shape = "decelerating"
    elif delta >= DELTA_AIC:
        shape = "nonlinear"
    else:
        shape = "linear"
    return NonlinearResult(
        years=[int(g) for g in grid],
        curve=curve.tolist(),
        curve_low=(curve - Z_CRIT * c_sd).tolist(),
        curve_high=(curve + Z_CRIT * c_sd).tolist(),
        derivative_per_decade=(deriv * 10).tolist(),
        derivative_low=((deriv - Z_CRIT * d_sd) * 10).tolist(),
        derivative_high=((deriv + Z_CRIT * d_sd) * 10).tolist(),
        edf=edf,
        smoothing=lam,
        aic_linear=float(aic_lin),
        aic_spline=float(aic_spl),
        delta_aic=delta,
        change_z=float(z),
        shape=shape,
    )
