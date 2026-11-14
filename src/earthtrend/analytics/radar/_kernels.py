"""numba kernel for radar stage 1: MK-AR1 + Sen on many short yearly series (section 9.2).

One row = annual (or seasonal) means of one series. Per row, over the finite values:
* Mann-Kendall S with the tie-corrected variance (``trend/mann_kendall.py``);
* lag-1 autocorrelation of the ranks of the Sen-detrended series on the compressed index,
  ``tie_key`` quantization, Var*(S) = Var(S) * max((1 + r1) / (1 - r1), 1) (199 if r1 >= 0.99);
* Sen's slope on the real time axis with the Gilbert CI (``trend/sen.py``).

The arithmetic mirrors ``mk_ar1`` + ``sen_slope``; ``test_radar_scan.py`` checks agreement
row by row. p-values are computed outside.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit, prange

SEN, CI_LO, CI_HI, Z_MK, N = range(5)
N_OUT = 5


@njit(cache=True)
def _interp_rank(srt: np.ndarray, n: int, rank: float) -> float:
    r = min(max(rank, 1.0), float(n)) - 1.0
    lo = int(math.floor(r))
    hi = min(lo + 1, n - 1)
    w = r - lo
    return srt[lo] * (1.0 - w) + srt[hi] * w


@njit(cache=True)
def _median_sorted(srt: np.ndarray, n: int) -> float:
    if n % 2 == 1:
        return srt[n // 2]
    return 0.5 * (srt[n // 2 - 1] + srt[n // 2])


@njit(cache=True)
def _one_row(
    y: np.ndarray, t: np.ndarray, z_crit: float, tie_resolution: float, out: np.ndarray
) -> None:
    for k in range(N_OUT):
        out[k] = np.nan
    ny = y.size
    m = 0
    for i in range(ny):
        if not math.isnan(y[i]):
            m += 1
    out[N] = m
    if m < 4:
        return
    v = np.empty(m)
    tv = np.empty(m)
    j = 0
    for i in range(ny):
        if not math.isnan(y[i]):
            v[j] = y[i]
            tv[j] = t[i]
            j += 1
    constant = True
    for a in range(1, m):
        if v[a] != v[0]:
            constant = False
            break
    if constant:
        return

    npairs = m * (m - 1) // 2
    s_stat = 0.0
    idx_slopes = np.empty(npairs)
    t_slopes = np.empty(npairs)
    nt = 0
    p = 0
    for a in range(m - 1):
        for b in range(a + 1, m):
            d = v[b] - v[a]
            if d > 0:
                s_stat += 1.0
            elif d < 0:
                s_stat -= 1.0
            idx_slopes[p] = d / (b - a)
            p += 1
            dt = tv[b] - tv[a]
            if dt != 0.0:
                t_slopes[nt] = d / dt
                nt += 1

    # Tie-corrected variance of S.
    vs = np.sort(v)
    tie_term = 0.0
    a = 0
    while a < m:
        b = a
        while b + 1 < m and vs[b + 1] == vs[a]:
            b += 1
        cnt = b - a + 1
        if cnt > 1:
            tie_term += cnt * (cnt - 1) * (2 * cnt + 5)
        a = b + 1
    var0 = (m * (m - 1) * (2 * m + 5) - tie_term) / 18.0

    # Rank lag-1 autocorrelation of the Sen-detrended series (compressed index).
    sen_idx = _median_sorted(np.sort(idx_slopes), npairs)
    det = np.empty(m)
    scale = 0.0
    for a in range(m):
        det[a] = v[a] - sen_idx * a
        scale = max(scale, abs(det[a]))
    if scale > 0:
        for a in range(m):
            det[a] = np.round(det[a] / scale * tie_resolution)
    order = np.argsort(det, kind="mergesort")
    ranks = np.empty(m)
    a = 0
    while a < m:
        b = a
        while b + 1 < m and det[order[b + 1]] == det[order[a]]:
            b += 1
        avg = (a + b) / 2.0 + 1.0
        for q in range(a, b + 1):
            ranks[order[q]] = avg
        a = b + 1
    rbar = 0.0
    for a in range(m):
        rbar += ranks[a]
    rbar /= m
    num = 0.0
    den = 0.0
    for a in range(m):
        den += (ranks[a] - rbar) ** 2
        if a > 0:
            num += (ranks[a - 1] - rbar) * (ranks[a] - rbar)
    r1 = num / den if den > 0 else 0.0
    factor = 199.0 if r1 >= 0.99 else max((1 + r1) / (1 - r1), 1.0)
    var_s = var0 * factor
    if s_stat > 0:
        z = (s_stat - 1.0) / math.sqrt(var_s)
    elif s_stat < 0:
        z = (s_stat + 1.0) / math.sqrt(var_s)
    else:
        z = 0.0
    out[Z_MK] = z

    if nt == 0:
        return
    srt = np.sort(t_slopes[:nt])
    out[SEN] = _median_sorted(srt, nt)
    c = z_crit * math.sqrt(max(var_s, 0.0))
    out[CI_LO] = _interp_rank(srt, nt, (nt - c) / 2.0)
    out[CI_HI] = _interp_rank(srt, nt, (nt + c) / 2.0 + 1.0)


@njit(parallel=True, cache=True)
def yearly_trends(y: np.ndarray, t: np.ndarray, z_crit: float, tie_resolution: float) -> np.ndarray:
    """``y``: (rows, years) contiguous, NaN = gap; ``t``: (years,). Returns (rows, N_OUT)."""
    nr = y.shape[0]
    out = np.empty((nr, N_OUT))
    for r in prange(nr):
        _one_row(y[r], t, z_crit, tie_resolution, out[r])
    return out
