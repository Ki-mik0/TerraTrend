"""GLSAR (feasible GLS with AR(1) errors, iterated Cochrane-Orcutt) for "Expert" (5.1 step 7).

A second opinion to OLS + n_eff: the AR(1) structure is modelled instead of corrected for.
Gaps are dropped (the series is treated as contiguous).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from earthtrend.analytics.preprocess.aggregate import FloatArray


@dataclass(frozen=True)
class GlsarFit:
    """GLSAR trend estimate: slope per year, 95% CI, p-value, t, AR(1) coefficient rho, n."""

    slope: float  # per year
    ci95: tuple[float, float]
    p_value: float
    t_stat: float
    rho: float
    n: int


def glsar_trend(t: FloatArray, y: FloatArray, maxiter: int = 10) -> GlsarFit | None:
    """Linear trend with AR(1) errors by feasible GLS (iterated Cochrane-Orcutt).

    Model: y_t = a + b t + u_t, u_t = rho u_(t-1) + e_t. Each iteration estimates rho from
    the residuals and refits OLS on quasi-differenced data y_t - rho y_(t-1).
    Uses statsmodels GLSAR. Returns None for fewer than 10 valid points.
    """
    from statsmodels.regression.linear_model import GLSAR

    ok = np.isfinite(t) & np.isfinite(y)
    if ok.sum() < 10:
        return None
    tv = t[ok] - t[ok].mean()
    x = np.column_stack([np.ones_like(tv), tv])
    model = GLSAR(y[ok], x, rho=1)
    res = model.iterative_fit(maxiter=maxiter)
    lo, hi = res.conf_int(alpha=0.05)[1]
    return GlsarFit(
        slope=float(res.params[1]),
        ci95=(float(lo), float(hi)),
        p_value=float(res.pvalues[1]),
        t_stat=float(res.tvalues[1]),
        rho=float(np.atleast_1d(model.rho)[0]),
        n=int(ok.sum()),
    )
