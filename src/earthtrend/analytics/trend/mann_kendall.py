"""Mann-Kendall test with an AR(1) variance correction on ranks (section 5.2).

Why not plain Hamed-Rao: in our Monte-Carlo check (40 years monthly, 300-400 runs per
setting) ``pymannkendall.hamed_rao_modification_test`` gave 9% false alarms on white noise
and 15% at AR(1) phi=0.6, and sometimes a negative Var(S). Our own Hamed-Rao with
significant lags only (lags 1..10 log10 n) still reached 10% at phi=0.8, because it drops
the long tail of the autocorrelation.

What we do (variance-correction family of Hamed & Rao 1998 / Yue & Wang 2004, with the
AR(1) closed form, consistent with the OLS n_eff correction):
1. detrend with Sen's slope, rank the residual series;
2. r1 = lag-1 autocorrelation of the ranks;
3. Var*(S) = Var(S) * (1 + r1) / (1 - r1), never below Var(S).

Measured false-alarm rate: 4.5% (phi=0), 5.2% (0.3), 5.8% (0.6), 6.5% (0.8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from earthtrend.analytics.preprocess.aggregate import FloatArray

MAX_CORRECTION = 199.0  # r1 -> 1 guard


@dataclass(frozen=True)
class MkResult:
    p_value: float
    z: float
    s: float
    var_s: float  # corrected variance of S (reused for the Sen CI)
    var_s_independent: float
    correction: float  # Var*(S) / Var(S)
    rank_r1: float
    tau: float
    n: int


@lru_cache(maxsize=64)
def pair_indices(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Cached (i, j) with i < j; read-only arrays."""
    i, j = np.triu_indices(n, k=1)
    i.setflags(write=False)
    j.setflags(write=False)
    return i, j


def average_ranks(x: FloatArray) -> FloatArray:
    """1-based ranks, ties get their average rank (= scipy.stats.rankdata default)."""
    n = x.size
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    starts = np.r_[0, np.flatnonzero(np.diff(xs)) + 1]
    ends = np.r_[starts[1:], n]
    ranks = np.empty(n)
    ranks[order] = np.repeat((starts + ends - 1) / 2.0 + 1.0, ends - starts)
    return ranks


def _s_statistic(v: FloatArray) -> float:
    i, j = pair_indices(v.size)
    return float(np.sign(v[j] - v[i]).sum())


def _variance_independent(v: FloatArray) -> float:
    n = v.size
    _, counts = np.unique(v, return_counts=True)
    ties = counts[counts > 1].astype(np.float64)
    return float((n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0)


TIE_RESOLUTION = 1e9  # values closer than max|d| / 1e9 count as tied


def tie_key(d: FloatArray) -> FloatArray:
    """Quantize detrended values so float noise cannot break a true tie.

    The pair of points that defines Sen's median slope has mathematically equal detrended
    values; without quantizing, whether they tie depends on the last bit of rounding.
    The grid kernel uses the same rule, so both give identical ranks.
    """
    scale = float(np.max(np.abs(d))) if d.size else 0.0
    return np.round(d / scale * TIE_RESOLUTION) if scale > 0 else d


def rank_lag1_autocorrelation(v: FloatArray) -> float:
    """Lag-1 autocorrelation of the ranks of the Sen-detrended series."""
    n = v.size
    idx = np.arange(n, dtype=np.float64)
    i, j = pair_indices(n)
    sen = float(np.median((v[j] - v[i]) / (j - i)))
    r = average_ranks(tie_key(v - sen * idx))
    x = r - r.mean()
    denom = float(np.sum(x * x))
    return float(np.sum(x[:-1] * x[1:]) / denom) if denom > 0 else 0.0


def mk_ar1(y: FloatArray) -> MkResult | None:
    """Gaps (NaN) are skipped; the series is treated as equally spaced."""
    v = np.asarray(y, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = v.size
    if n < 4 or np.all(v == v[0]):
        return None
    s = _s_statistic(v)
    var0 = _variance_independent(v)
    r1 = rank_lag1_autocorrelation(v)
    factor = MAX_CORRECTION if r1 >= 0.99 else max((1 + r1) / (1 - r1), 1.0)
    var_s = var0 * factor
    z = (s - math.copysign(1.0, s)) / math.sqrt(var_s) if s != 0 else 0.0
    return MkResult(
        p_value=math.erfc(abs(z) / math.sqrt(2.0)),  # = 2 * norm.sf(|z|), no scipy overhead
        z=z,
        s=s,
        var_s=var_s,
        var_s_independent=var0,
        correction=factor,
        rank_r1=r1,
        tau=s / (n * (n - 1) / 2),
        n=n,
    )
