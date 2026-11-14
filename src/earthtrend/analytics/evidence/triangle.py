"""Trend triangle (section 6.3): is the trend robust to the choice of period?

All (start, end) windows of >= 15 years (>= 10 for records < 25 years) on annual means.
OLS slope per window; Mann-Kendall S per window from 2-D prefix sums of the pairwise sign
matrix (no per-window O(n^2) work). Plain MK variance: annual values, short windows.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from earthtrend.analytics.models import ItemStatus, TriangleResult
from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray

SIG_P = 0.10
PASS_SAME, PASS_SIG, PARTIAL_SAME = 0.9, 0.6, 0.7


def _min_window(n_years: int) -> int:
    return 15 if n_years >= 25 else 10


def trend_triangle(
    years: IntArray, annual: FloatArray, reference_sign: int
) -> TriangleResult | None:
    n = annual.size
    w_min = _min_window(n)
    if n < w_min or reference_sign == 0:
        return None
    ok = np.isfinite(annual)
    a = np.where(ok, annual, 0.0)
    sign = np.sign(a[None, :] - a[:, None])
    sign *= ok[:, None] & ok[None, :]
    sign = np.triu(sign, k=1)
    c = np.zeros((n + 1, n + 1))
    c[1:, 1:] = sign.cumsum(0).cumsum(1)
    cnt = np.r_[0, ok.cumsum()]
    t = years.astype(np.float64)

    slopes: list[list[float | None]] = [[None] * n for _ in range(n)]
    pvals: list[list[float | None]] = [[None] * n for _ in range(n)]
    same = sig_same = total = 0
    for s in range(n):
        for e in range(s + w_min - 1, n):
            m = int(cnt[e + 1] - cnt[s])
            if m < max(8, int(0.8 * (e - s + 1))):
                continue
            sel = ok[s : e + 1]
            tv, yv = t[s : e + 1][sel], annual[s : e + 1][sel]
            dt = tv - tv.mean()
            slope = float(np.dot(dt, yv - yv.mean()) / np.dot(dt, dt))
            s_stat = c[e + 1, e + 1] - c[s, e + 1] - c[e + 1, s] + c[s, s]
            var = m * (m - 1) * (2 * m + 5) / 18.0
            z = (s_stat - np.sign(s_stat)) / np.sqrt(var) if s_stat else 0.0
            p = float(2 * stats.norm.sf(abs(z)))
            slopes[s][e] = slope * 10
            pvals[s][e] = p
            total += 1
            if np.sign(slope) == reference_sign:
                same += 1
                if p < SIG_P:
                    sig_same += 1
    if total == 0:
        return None
    return TriangleResult(
        years=[int(y) for y in years],
        min_window=w_min,
        slope_per_decade=slopes,
        p_mk=pvals,
        n_windows=total,
        same_sign_share=same / total,
        sig_same_sign_share=sig_same / total,
    )


def triangle_status(tri: TriangleResult | None) -> ItemStatus:
    if tri is None:
        return "na"
    if tri.same_sign_share >= PASS_SAME and tri.sig_same_sign_share >= PASS_SIG:
        return "pass"
    if tri.same_sign_share >= PARTIAL_SAME:
        return "partial"
    return "fail"
