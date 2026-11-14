"""Change points of the trend component (section 5.6).

Main method: BEAST (Rbeast, MIT licence), Bayesian model averaging of piecewise trends;
points with posterior probability > 0.5 are reported, seeded for reproducibility.
Fallback when Rbeast is unavailable or fails: PELT (ruptures, L2 cost, BIC-like penalty).

Input is placed on a regular time axis (monthly, or annual for seasonal cases); missing
steps are NaN, which BEAST handles natively.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

from earthtrend.analytics.models import Changepoint
from earthtrend.analytics.preprocess.aggregate import FloatArray

MIN_PROBABILITY = 0.5
PELT_MIN_SIZE = 24


def _to_date(x: float, step: float, label_month: int) -> date:
    year = int(math.floor(x))
    if step >= 1.0:
        return date(year, label_month, 1)
    month = int(round((x - year) * 12 + 0.5))
    if month > 12:
        year, month = year + 1, 1
    return date(year, max(month, 1), 1)


def _regular(t: FloatArray, y: FloatArray, step: float) -> tuple[FloatArray, FloatArray]:
    k = np.rint((t - t[0]) / step).astype(np.int64)
    grid = t[0] + step * np.arange(k[-1] + 1)
    out = np.full(grid.size, np.nan)
    out[k] = y
    return grid, out


def _beast(
    grid: FloatArray, y: FloatArray, step: float, seed: int
) -> list[tuple[float, float, tuple[float, float] | None, float | None]]:
    import Rbeast as rb

    o = rb.beast(
        y,
        start=float(grid[0]),
        deltat=step,
        season="none",
        quiet=1,
        print_progress=0,
        print_options=0,
        mcmc_seed=seed,
    )
    tr = o.trend
    out = []
    cps = np.atleast_1d(tr.cp)
    prs = np.atleast_1d(tr.cpPr)
    cis = np.atleast_2d(tr.cpCI) if tr.cpCI is not None else None
    jumps = np.atleast_1d(tr.cpAbruptChange) if tr.cpAbruptChange is not None else None
    for i, (cp, pr) in enumerate(zip(cps, prs, strict=False)):
        if not (np.isfinite(cp) and np.isfinite(pr)) or pr <= MIN_PROBABILITY:
            continue
        ci = (float(cis[i][0]), float(cis[i][1])) if cis is not None and i < len(cis) else None
        jump = float(jumps[i]) if jumps is not None and np.isfinite(jumps[i]) else None
        out.append((float(cp), float(pr), ci, jump))
    return out


def _pelt(grid: FloatArray, y: FloatArray) -> list[float]:
    import ruptures as rpt

    ok = np.isfinite(y)
    if ok.sum() < 2 * PELT_MIN_SIZE:
        return []
    x = np.interp(np.arange(y.size), np.flatnonzero(ok), y[ok])
    d = np.diff(x)
    sigma = 1.4826 * float(np.median(np.abs(d - np.median(d)))) / math.sqrt(2)
    pen = 3 * max(sigma, 1e-12) ** 2 * math.log(x.size)
    bkps = rpt.Pelt(model="l2", min_size=PELT_MIN_SIZE).fit(x).predict(pen=pen)
    return [float(grid[b]) for b in bkps if b < x.size]


def detect_changepoints(
    t: FloatArray, y: FloatArray, step: float, label_month: int = 1, seed: int = 42
) -> list[Changepoint]:
    ok = np.isfinite(t)
    t, y = t[ok], y[ok]
    if t.size < 24 or np.isfinite(y).sum() < 24:
        return []
    grid, yr = _regular(t, y, step)
    try:
        found = _beast(grid, yr, step, seed)
        return [
            Changepoint(
                at=_to_date(cp, step, label_month),
                probability=pr,
                ci=(_to_date(ci[0], step, label_month), _to_date(ci[1], step, label_month))
                if ci
                else None,
                jump=jump,
                method="beast",
            )
            for cp, pr, ci, jump in sorted(found)
        ]
    except Exception:  # noqa: BLE001 - any Rbeast failure falls back to PELT
        return [
            Changepoint(
                at=_to_date(cp, step, label_month),
                probability=None,
                ci=None,
                jump=None,
                method="pelt",
            )
            for cp in _pelt(grid, yr)
        ]
