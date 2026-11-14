"""Trends on a grid (docs/PLAN_ANALYTICS.md section 8.1).

Per cell, with the same conventions as the series core:
* monthly anomalies (per-cell monthly climatology over the baseline);
* OLS + AR(1) n_eff on the monthly anomalies (identical to ``trend/ols.py``);
* Mann-Kendall with the AR(1) rank correction and Sen's slope + Gilbert CI on
  **annual means** (validity rules of section 4.1). Annual means keep the pairwise work
  at ~1k pairs per cell instead of ~145k for monthly data;
* a cell with > 20% missing months is NaN.

Gaps inside an annual series: Mann-Kendall and Sen skip them; the rank lag-1
autocorrelation only uses consecutive years that both exist (the series core compresses
gaps instead; with no missing years both agree exactly).

Numerics run in a numba kernel (``_kernels.py``), parallel over cells, in chunks to bound
memory. p-values are computed here with scipy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from earthtrend.analytics import config
from earthtrend.analytics.preprocess.aggregate import decimal_year, split_dates
from earthtrend.analytics.spatial import _kernels as k
from earthtrend.analytics.trend.mann_kendall import TIE_RESOLUTION

F = NDArray[np.float64]
B = NDArray[np.bool_]

CHUNK_CELLS = 65_536  # 65k cells x 540 months x 8 B = 280 MB per chunk


@dataclass(frozen=True)
class GridTrendFields:
    """Per-cell results, each of shape (lat, lon); NaN where not computed."""

    slope: F  # Sen's slope per decade (annual means)
    ci_low: F
    ci_high: F
    slope_ols: F  # OLS slope per decade (monthly anomalies)
    p_ols: F
    p_mk: F
    n_eff: F
    snr: F  # |Sen slope per decade| / sigma of monthly anomalies
    valid: B


def _season_of_month() -> NDArray[np.int64]:
    som = np.zeros(12, dtype=np.int64)
    for q, months in enumerate(config.SEASON_MONTHS.values()):
        for m in months:
            som[m - 1] = q
    return som


def grid_trends(
    cube: F,
    dates: Sequence[date],
    cell_mask: B | None = None,
    baseline: tuple[int, int] | None = None,
    alpha: float = config.ALPHA,
) -> GridTrendFields:
    """``cube``: monthly values (time, lat, lon). ``cell_mask``: cells to compute."""
    cube = np.asarray(cube, dtype=np.float64)
    nt, nlat, nlon = cube.shape
    if nt != len(dates):
        raise ValueError("cube time axis and dates differ in length")
    years, months = split_dates(dates)
    if np.any(np.diff(years) < 0):
        raise ValueError("dates must be increasing")
    t = decimal_year(years, months)
    base = (years >= baseline[0]) & (years <= baseline[1]) if baseline else np.ones(nt, dtype=bool)
    year_start = np.r_[0, np.flatnonzero(np.diff(years)) + 1, nt].astype(np.int64)
    month0 = (months - 1).astype(np.int64)
    som = _season_of_month()
    z_crit = float(stats.norm.ppf(1 - alpha / 2))

    flat = cube.reshape(nt, -1)
    sel = np.ones(flat.shape[1], bool) if cell_mask is None else np.asarray(cell_mask).ravel()
    gap = np.mean(~np.isfinite(flat), axis=0)
    todo = np.flatnonzero(sel & (gap <= config.MAX_GAP_SHARE))

    res = np.full((flat.shape[1], k.N_OUT), np.nan)
    for start in range(0, todo.size, CHUNK_CELLS):
        cells = todo[start : start + CHUNK_CELLS]
        y = np.ascontiguousarray(flat[:, cells].T)
        res[cells] = k.cell_trends(
            y,
            t,
            month0,
            base,
            year_start,
            som,
            config.N_EFF_MIN,
            config.ANNUAL_MIN_MONTHS,
            z_crit,
            TIE_RESOLUTION,
        )

    with np.errstate(invalid="ignore"):
        p_ols = 2 * stats.t.sf(np.abs(res[:, k.T_OLS]), res[:, k.DOF_OLS])
        p_mk = 2 * stats.norm.sf(np.abs(res[:, k.Z_MK]))
    sen = res[:, k.SEN]
    valid = np.isfinite(sen) & np.isfinite(p_ols)
    sigma = res[:, k.SIGMA]
    with np.errstate(invalid="ignore", divide="ignore"):
        snr = np.where(sigma > 0, np.abs(sen * 10) / sigma, np.nan)

    def _grid(v: F) -> F:
        return np.where(valid, v, np.nan).reshape(nlat, nlon)

    return GridTrendFields(
        slope=_grid(sen * 10),
        ci_low=_grid(res[:, k.CI_LO] * 10),
        ci_high=_grid(res[:, k.CI_HI] * 10),
        slope_ols=_grid(res[:, k.SLOPE_OLS] * 10),
        p_ols=_grid(p_ols),
        p_mk=_grid(p_mk),
        n_eff=_grid(res[:, k.N_EFF]),
        snr=_grid(snr),
        valid=valid.reshape(nlat, nlon),
    )
