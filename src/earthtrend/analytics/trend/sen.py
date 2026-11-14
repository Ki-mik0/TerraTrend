"""Sen's slope with a confidence interval from the autocorrelation-corrected variance of S.

Section 5.3; CI construction after Gilbert (1987): with N pairwise slopes sorted,
C = z_(1-alpha/2) * sqrt(Var(S)), the bounds are the (N - C)/2-th and (N + C)/2 + 1-th slopes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy import stats

from earthtrend.analytics.preprocess.aggregate import FloatArray


@dataclass(frozen=True)
class SenResult:
    """Sen slope (units per year), intercept median(y - slope t), 95% CI, n (Sen 1968)."""

    slope: float  # units per year
    intercept: float
    ci95: tuple[float, float]
    n: int


@lru_cache(maxsize=16)
def _z(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def sen_slope(t: FloatArray, y: FloatArray, var_s: float, alpha: float = 0.05) -> SenResult | None:
    """Theil-Sen slope with a rank-based confidence interval.

    slope = median((y_j - y_i) / (t_j - t_i)) over pairs i < j (Sen 1968).
    CI (Gilbert 1987): C = z_(1-alpha/2) * sqrt(Var(S)); bounds are the (N - C)/2-th and
    (N + C)/2 + 1-th sorted pairwise slopes (interpolated), N = number of pairs.
    ``var_s`` is the (autocorrelation-corrected) variance of the MK statistic S.
    """
    ok = np.isfinite(y) & np.isfinite(t)
    tv, yv = t[ok], y[ok]
    n = tv.size
    if n < 3:
        return None
    i, j = np.triu_indices(n, k=1)
    dt = tv[j] - tv[i]
    keep = dt != 0
    slopes = np.sort((yv[j] - yv[i])[keep] / dt[keep])
    n_pairs = slopes.size
    if n_pairs == 0:
        return None
    slope = float(np.median(slopes))
    intercept = float(np.median(yv - slope * tv))

    c = _z(alpha) * float(np.sqrt(max(var_s, 0.0)))
    ranks = np.arange(1, n_pairs + 1, dtype=np.float64)
    lo_rank = np.clip((n_pairs - c) / 2.0, 1, n_pairs)
    hi_rank = np.clip((n_pairs + c) / 2.0 + 1.0, 1, n_pairs)
    lo = float(np.interp(lo_rank, ranks, slopes))
    hi = float(np.interp(hi_rank, ranks, slopes))
    return SenResult(slope=slope, intercept=intercept, ci95=(lo, hi), n=n)
