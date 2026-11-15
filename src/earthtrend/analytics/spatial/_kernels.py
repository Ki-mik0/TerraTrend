"""numba kernel for per-cell trends (section 8.1). Pure numerics, no p-values.

One fused pass per cell, parallel over cells:
climatology -> monthly anomalies -> sigma -> OLS + AR(1) n_eff -> annual means (section 4.1)
-> Mann-Kendall S + AR(1) rank correction -> Sen's slope + Gilbert CI.
p-values are computed outside with scipy (``grid_trend.py``).

The arithmetic mirrors ``trend/ols.py``, ``trend/mann_kendall.py`` and ``trend/sen.py``;
``tests/analytics/unit/test_grid.py`` checks cell-by-cell agreement.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit, prange

# Output columns of ``cell_trends``.
SEN, CI_LO, CI_HI, SLOPE_OLS, T_OLS, DOF_OLS, N_EFF, Z_MK, SIGMA, N_YEARS = range(10)
N_OUT = 10


@njit(cache=True)
def _order_stat(srt: np.ndarray, n: int, rank: float) -> float:
    r = min(max(rank, 1.0), float(n)) - 1.0
    lo = int(math.floor(r))
    hi = min(lo + 1, n - 1)
    w = r - lo
    return srt[lo] * (1.0 - w) + srt[hi] * w


@njit(cache=True)
def _one_cell(
    y: np.ndarray,
    t: np.ndarray,
    month0: np.ndarray,
    base: np.ndarray,
    year_start: np.ndarray,
    season_of_month: np.ndarray,
    season_need: np.ndarray,
    n_eff_min: float,
    annual_min_months: int,
    z_crit: float,
    tie_resolution: float,
    out: np.ndarray,
) -> None:
    nt = y.size
    for k in range(N_OUT):
        out[k] = np.nan

    # Climatology over the baseline, anomalies.
    csum = np.zeros(12)
    ccnt = np.zeros(12)
    for i in range(nt):
        if base[i] and not math.isnan(y[i]):
            csum[month0[i]] += y[i]
            ccnt[month0[i]] += 1.0
    anom = np.empty(nt)
    for i in range(nt):
        c = ccnt[month0[i]]
        anom[i] = y[i] - csum[month0[i]] / c if c > 0 else np.nan

    # OLS on monthly anomalies.
    n = 0
    st = 0.0
    sy = 0.0
    for i in range(nt):
        if not math.isnan(anom[i]):
            n += 1
            st += t[i]
            sy += anom[i]
    if n < 3:
        return
    tbar = st / n
    ybar = sy / n
    sxx = 0.0
    sxy = 0.0
    for i in range(nt):
        if not math.isnan(anom[i]):
            dt = t[i] - tbar
            sxx += dt * dt
            sxy += dt * (anom[i] - ybar)
    if sxx == 0.0:
        return
    slope = sxy / sxx
    sse = 0.0
    var_a = 0.0
    for i in range(nt):
        if not math.isnan(anom[i]):
            e = anom[i] - (ybar + slope * (t[i] - tbar))
            sse += e * e
            var_a += (anom[i] - ybar) ** 2
    mean_res = 0.0  # OLS residuals have zero mean over the valid points
    pair_sum = 0.0
    n_pairs = 0
    prev = np.nan
    for i in range(nt):
        cur = anom[i] - (ybar + slope * (t[i] - tbar)) if not math.isnan(anom[i]) else np.nan
        if i > 0 and not math.isnan(cur) and not math.isnan(prev):
            pair_sum += (prev - mean_res) * (cur - mean_res)
            n_pairs += 1
        prev = cur
    var_r = sse / n
    r1 = pair_sum / n_pairs / var_r if (n_pairs >= 3 and var_r > 0) else 0.0
    n_eff = n * (1 - r1) / (1 + r1) if r1 > 0 else float(n)
    n_eff = min(max(n_eff, n_eff_min), max(float(n), n_eff_min))
    se = math.sqrt(sse / (n_eff - 2.0) / sxx)
    out[SLOPE_OLS] = slope
    out[DOF_OLS] = n_eff - 2.0
    out[N_EFF] = n_eff
    if se == 0.0:
        out[T_OLS] = np.inf if slope != 0 else 0.0
    else:
        out[T_OLS] = slope / se
    out[SIGMA] = math.sqrt(var_a / (n - 1)) if n > 1 else np.nan

    # Annual means with validity rules.
    ny = year_start.size - 1
    ann = np.empty(ny)
    for k in range(ny):
        cnt = 0
        s = 0.0
        seas = np.zeros(4)
        for i in range(year_start[k], year_start[k + 1]):
            if not math.isnan(anom[i]):
                cnt += 1
                s += anom[i]
                seas[season_of_month[month0[i]]] += 1.0
        ok = cnt >= annual_min_months
        for q in range(4):
            if season_need[q] - seas[q] >= 2.0:
                ok = False
        ann[k] = s / cnt if ok else np.nan

    # Mann-Kendall + Sen on the valid annual values.
    m = 0
    for k in range(ny):
        if not math.isnan(ann[k]):
            m += 1
    if m < 4:
        return
    vals = np.empty(m)
    idx = np.empty(m)
    j = 0
    for k in range(ny):
        if not math.isnan(ann[k]):
            vals[j] = ann[k]
            idx[j] = k
            j += 1
    npairs = m * (m - 1) // 2
    slopes = np.empty(npairs)
    s_stat = 0.0
    p = 0
    for a in range(m - 1):
        for b in range(a + 1, m):
            d = vals[b] - vals[a]
            if d > 0:
                s_stat += 1.0
            elif d < 0:
                s_stat -= 1.0
            slopes[p] = d / (idx[b] - idx[a])
            p += 1
    srt = np.sort(slopes)
    sen = _order_stat(srt, npairs, (npairs + 1) / 2.0)

    # Ranks of the Sen-detrended series; lag-1 over consecutive years that both exist.
    det = np.empty(m)
    for a in range(m):
        det[a] = vals[a] - sen * idx[a]
    # Same tie rule as ``trend.mann_kendall.tie_key``.
    scale = 0.0
    for a in range(m):
        scale = max(scale, abs(det[a]))
    if scale > 0:
        for a in range(m):
            det[a] = np.round(det[a] / scale * tie_resolution)
    order = np.argsort(det, kind="mergesort")
    # Average ranks for exact ties, as scipy.stats.rankdata(method="average"). A tie always
    # exists: the pair defining Sen's median slope has equal detrended values.
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
    rbar = (m + 1) / 2.0
    num = 0.0
    den = 0.0
    for a in range(m):
        den += (ranks[a] - rbar) ** 2
        if a > 0 and idx[a] == idx[a - 1] + 1:
            num += (ranks[a - 1] - rbar) * (ranks[a] - rbar)
    rr = num / den if den > 0 else 0.0
    factor = 199.0 if rr >= 0.99 else max((1 + rr) / (1 - rr), 1.0)
    var_s = m * (m - 1) * (2 * m + 5) / 18.0 * factor
    if s_stat > 0:
        z = (s_stat - 1.0) / math.sqrt(var_s)
    elif s_stat < 0:
        z = (s_stat + 1.0) / math.sqrt(var_s)
    else:
        z = 0.0
    c = z_crit * math.sqrt(var_s)
    out[SEN] = sen
    out[CI_LO] = _order_stat(srt, npairs, (npairs - c) / 2.0)
    out[CI_HI] = _order_stat(srt, npairs, (npairs + c) / 2.0 + 1.0)
    out[Z_MK] = z
    out[N_YEARS] = m


@njit(parallel=True, cache=True)
def cell_trends(
    y: np.ndarray,  # (cells, time), contiguous
    t: np.ndarray,
    month0: np.ndarray,  # 0..11
    base: np.ndarray,
    year_start: np.ndarray,  # row offsets of each calendar year, + final length
    season_of_month: np.ndarray,  # (12,) 0..3
    season_need: np.ndarray,  # (4,) months each season should have; 0 = not required
    n_eff_min: float,
    annual_min_months: int,
    z_crit: float,
    tie_resolution: float,
) -> np.ndarray:
    """numba kernel, parallel over cells (section 8.1): OLS + AR(1) n_eff on monthly
    anomalies, MK-AR1 and Sen (Gilbert CI) on annual means; one output row per cell.
    """
    nc = y.shape[0]
    out = np.empty((nc, N_OUT))
    for c in prange(nc):
        _one_cell(
            y[c],
            t,
            month0,
            base,
            year_start,
            season_of_month,
            season_need,
            n_eff_min,
            annual_min_months,
            z_crit,
            tie_resolution,
            out[c],
        )
    return out
