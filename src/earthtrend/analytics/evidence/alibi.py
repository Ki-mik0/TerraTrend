"""Alibi (section 6.4): is the trend still there once known climate modes are accounted for?

    y(t) = a + b t + sum_k c_k index_k(t - lag_k) + e(t)

* Lag from {0, 2, 4, 6} months, chosen on *detrended* series (max |correlation|).
* An index is kept only if it improves prediction of held-out years (contiguous year
  blocks, 5-fold), added greedily in order of correlation. At most three indices.
* Standard error of b: Newey-West HAC, L = floor(4 (n/100)^(2/9)).
* ``trend_overlap_r`` = corr(index, time); |r| > 0.3 gives ``index_trend_overlap``.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from scipy import stats

from earthtrend.analytics import config
from earthtrend.analytics.models import AlibiResult, AlibiTerm, ClimateIndex, ItemStatus
from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray

LAGS = (0, 2, 4, 6)
MAX_INDICES = 3
N_FOLDS = 5
OVERLAP_R = 0.3
MIN_OVERLAP = 0.8  # share of series months with index values at a lag


def _aligned(index: ClimateIndex, years: IntArray, months: IntArray, lag: int) -> FloatArray:
    table = {
        d.year * 12 + d.month - 1: v
        for d, v in zip(index.dates, index.values, strict=True)
        if v is not None
    }
    key = years * 12 + months - 1 - lag
    return np.array([table.get(int(k), np.nan) for k in key], dtype=np.float64)


def _detrend(t: FloatArray, y: FloatArray) -> FloatArray:
    ok = np.isfinite(y)
    out = np.full(y.shape, np.nan)
    if ok.sum() < 3:
        return out
    coef = np.polyfit(t[ok], y[ok], 1)
    out[ok] = y[ok] - np.polyval(coef, t[ok])
    return out


def _corr(a: FloatArray, b: FloatArray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return 0.0
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def _design(t: FloatArray, cols: list[FloatArray]) -> FloatArray:
    return np.column_stack([np.ones_like(t), t - t.mean(), *cols])


def _cv_mse(t: FloatArray, y: FloatArray, cols: list[FloatArray], years: IntArray) -> float:
    rows = np.isfinite(y)
    for c in cols:
        rows &= np.isfinite(c)
    uy = np.unique(years[rows])
    if uy.size < N_FOLDS * 2:
        return np.inf
    folds = np.array_split(uy, N_FOLDS)
    x = _design(t, cols)
    sse = 0.0
    n = 0
    for fold in folds:
        test = rows & np.isin(years, fold)
        train = rows & ~test
        beta, *_ = np.linalg.lstsq(x[train], y[train], rcond=None)
        r = y[test] - x[test] @ beta
        sse += float(r @ r)
        n += int(test.sum())
    return sse / n if n else np.inf


def _hac(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray, float]:
    """OLS with Newey-West covariance. Returns (beta, se, sse)."""
    n, k = x.shape
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    u = y - x @ beta
    lag = int(np.floor(4 * (n / 100) ** (2 / 9)))
    xu = x * u[:, None]
    s = xu.T @ xu
    for ell in range(1, lag + 1):
        w = 1 - ell / (lag + 1)
        g = xu[ell:].T @ xu[:-ell]
        s += w * (g + g.T)
    cov = xtx_inv @ s @ xtx_inv
    return beta, np.sqrt(np.diag(cov)), float(u @ u)


def alibi(
    t: FloatArray,
    anom: FloatArray,
    years: IntArray,
    months: IntArray,
    dates: list[date],
    indices: list[ClimateIndex],
    alpha: float = config.ALPHA,
) -> AlibiResult | None:
    """None when no indices are supplied (status ``na``)."""
    if not indices:
        return None
    y_dt = _detrend(t, anom)

    # Lag per index on detrended series.
    candidates: list[tuple[float, str, int, FloatArray]] = []
    for idx in indices[:MAX_INDICES]:
        best: tuple[float, int, FloatArray] | None = None
        for lag in LAGS:
            col = _aligned(idx, years, months, lag)
            if np.isfinite(col).mean() < MIN_OVERLAP:
                continue
            r = abs(_corr(y_dt, _detrend(t, col)))
            if best is None or r > best[0]:
                best = (r, lag, col)
        if best is not None:
            candidates.append((best[0], idx.name, best[1], best[2]))
    candidates.sort(key=lambda c: -c[0])

    # Greedy forward selection by held-out-year error.
    kept: list[tuple[str, int, FloatArray]] = []
    rejected: list[str] = [
        i.name for i in indices[:MAX_INDICES] if i.name not in {c[1] for c in candidates}
    ]
    current = _cv_mse(t, anom, [], years)
    for _, name, lag, col in candidates:
        trial = _cv_mse(t, anom, [k[2] for k in kept] + [col], years)
        if trial < current:
            kept.append((name, lag, col))
            current = trial
        else:
            rejected.append(name)

    cols = [k[2] for k in kept]
    rows = np.isfinite(anom)
    for c in cols:
        rows &= np.isfinite(c)
    if rows.sum() < 10:
        return None
    x_full = _design(t[rows], [c[rows] for c in cols])
    beta, se, sse_full = _hac(x_full, anom[rows])
    x_raw = _design(t[rows], [])
    beta_raw, _, sse_raw = _hac(x_raw, anom[rows])
    dof = max(int(rows.sum()) - x_full.shape[1], 1)
    p_adj = float(2 * stats.t.sf(abs(beta[1] / se[1]), dof)) if se[1] > 0 else 0.0

    adjusted = anom.copy()
    for c, coef in zip(cols, beta[2:], strict=True):
        adjusted = adjusted - coef * c
    terms = [
        AlibiTerm(
            index=name,
            lag_months=lag,
            coefficient=float(coef),
            trend_overlap_r=_corr(col, t),
        )
        for (name, lag, col), coef in zip(kept, beta[2:], strict=True)
    ]
    return AlibiResult(
        b_raw_per_decade=float(beta_raw[1] * 10),
        b_adjusted_per_decade=float(beta[1] * 10),
        p_adjusted=p_adj,
        se_adjusted_hac=float(se[1] * 10),
        partial_r2=float((sse_raw - sse_full) / sse_raw) if sse_raw > 0 else 0.0,
        terms=terms,
        rejected=rejected,
        adjusted_anomalies=[float(v) if np.isfinite(v) else None for v in adjusted],
        dates=dates,
    )


def alibi_status(res: AlibiResult | None, alpha: float = config.ALPHA) -> ItemStatus:
    if res is None:
        return "na"
    same = np.sign(res.b_adjusted_per_decade) == np.sign(res.b_raw_per_decade) != 0
    if same and res.p_adjusted < alpha:
        return "pass"
    if same:
        return "partial"
    return "fail"


def alibi_caveats(res: AlibiResult | None, status: ItemStatus) -> list[str]:
    if res is None:
        return []
    out = []
    if any(abs(t.trend_overlap_r) > OVERLAP_R for t in res.terms):
        out.append("index_trend_overlap")
    if status == "fail" and any(t.index == "nino34" for t in res.terms):
        out.append("explained_by_enso")
    return out
