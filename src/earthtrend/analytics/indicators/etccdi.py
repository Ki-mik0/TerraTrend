"""Derived climate indicators from daily data (docs/PLAN_ANALYTICS.md section 7).

Definitions follow the ETCCDI indices (Zhang et al., 2011, WIREs Climate Change 2:851;
https://etccdi.pacificclimate.org/list_27_indices.shtml) with the simplifications listed
in ``docs/methods/indicators.md``.

Every function takes a complete daily calendar ``dates`` (one entry per day, gaps as NaN in
``data``) and ``data`` of shape ``(n_days, ...)``: the trailing axes are grid cells, so the
same code serves a regional series (1-D) and a grid (``(n_days, lat, lon)``). The result is
``(years, annual)`` with ``annual`` of shape ``(n_years, ...)``. A year with fewer than
``config.DAILY_MIN_VALID`` valid days is NaN.

Units: temperature in degrees Celsius, precipitation in mm/day, snow cover as a fraction
(0..1). Analytics never guesses units; Kelvin input is rejected.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

WET_DAY_MM = 1.0  # ETCCDI wet day: precipitation >= 1 mm
TX90P_WINDOW = 5  # +-5 calendar days around each day of year
GSL_THRESHOLD_C = 5.0
GSL_SPAN_DAYS = 6
SNOW_COVER_THRESHOLD = 0.5  # section 7: snow cover > 50% of the cell
CELL_CHUNK_BYTES = 200 * 2**20  # memory budget of the TX90p in-base bootstrap per chunk


# ---------------------------------------------------------------- calendar helpers


def _check_calendar(dates: Sequence[date], data: FloatArray) -> FloatArray:
    data = np.asarray(data, dtype=np.float64)
    if data.shape[0] != len(dates):
        raise ValueError("data time axis and dates differ in length")
    if not dates:
        raise ValueError("empty series")
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:], strict=False)):
        raise ValueError("dates must be a complete daily calendar (gaps as NaN in data)")
    return data


def _check_celsius(data: FloatArray) -> None:
    med = np.nanmedian(data) if np.isfinite(data).any() else 0.0
    if med > 150.0:
        raise ValueError("temperature looks like Kelvin; convert to degrees Celsius first")


def year_blocks(dates: Sequence[date]) -> list[tuple[int, slice]]:
    """(year, slice of ``dates``) for every calendar year present."""
    years = np.fromiter((d.year for d in dates), dtype=np.int64, count=len(dates))
    starts = np.r_[0, np.flatnonzero(np.diff(years)) + 1]
    ends = np.r_[starts[1:], years.size]
    return [(int(years[s]), slice(int(s), int(e))) for s, e in zip(starts, ends, strict=True)]


def _days_in_year(y: int) -> int:
    return 366 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 365


def _valid_year(block: FloatArray, year: int) -> NDArray[np.bool_]:
    """Year counts only if >= DAILY_MIN_VALID of its calendar days have data."""
    n_valid = np.isfinite(block).sum(axis=0)
    return np.asarray(n_valid >= config.DAILY_MIN_VALID * _days_in_year(year))


def doy365(dates: Sequence[date]) -> IntArray:
    """Day of year on a 365-day calendar (0..364); 29 February shares 28 February."""
    out = np.empty(len(dates), dtype=np.int64)
    for k, d in enumerate(dates):
        j = d.timetuple().tm_yday - 1
        leap = _days_in_year(d.year) == 366
        if leap and j >= 59:  # 29 Feb (j = 59) -> 58, later days shift back by one
            j -= 1
        out[k] = j
    return out


def _annual(
    dates: Sequence[date],
    data: FloatArray,
    stat: object,
) -> tuple[IntArray, FloatArray]:
    blocks = year_blocks(dates)
    out = np.full((len(blocks), *data.shape[1:]), np.nan)
    for k, (y, sl) in enumerate(blocks):
        block = data[sl]
        val = stat(block)  # type: ignore[operator]
        out[k] = np.where(_valid_year(block, y), val, np.nan)
    return np.array([y for y, _ in blocks], dtype=np.int64), out


def nan_quantile(x: FloatArray, q: float, axis: int) -> FloatArray:
    """Linear-interpolation quantile ignoring NaN (= numpy ``nanpercentile(x, 100 q)``).

    ``np.nanpercentile`` loops over 1-D slices in Python for arrays with NaN, which made
    the TX90p bootstrap ~100x slower; this sorts once in C (NaN sort last).
    """
    xs = np.sort(x, axis=axis)
    n = np.isfinite(xs).sum(axis=axis, keepdims=True)
    pos = (np.maximum(n, 1) - 1) * q
    lo = np.floor(pos).astype(np.int64)
    hi = np.minimum(lo + 1, np.maximum(n - 1, 0))
    frac = pos - lo
    a = np.take_along_axis(xs, lo, axis=axis)
    b = np.take_along_axis(xs, hi, axis=axis)
    out = a + (b - a) * frac
    out = np.where(n > 0, out, np.nan)
    return np.squeeze(out, axis=axis)


# ---------------------------------------------------------------- simple counts


def frost_days(dates: Sequence[date], tmin: FloatArray) -> tuple[IntArray, FloatArray]:
    """FD: days with Tmin < 0 degC."""
    tmin = _check_calendar(dates, tmin)
    _check_celsius(tmin)
    with np.errstate(invalid="ignore"):
        return _annual(dates, tmin, lambda b: (b < 0.0).sum(axis=0).astype(np.float64))


def summer_days(dates: Sequence[date], tmax: FloatArray) -> tuple[IntArray, FloatArray]:
    """SU: days with Tmax > 25 degC."""
    tmax = _check_calendar(dates, tmax)
    _check_celsius(tmax)
    with np.errstate(invalid="ignore"):
        return _annual(dates, tmax, lambda b: (b > 25.0).sum(axis=0).astype(np.float64))


def snow_days(
    dates: Sequence[date], snow_cover: FloatArray, threshold: float = SNOW_COVER_THRESHOLD
) -> tuple[IntArray, FloatArray]:
    """SNOW_DAYS: days with snow cover above ``threshold`` (fraction of the cell)."""
    snow_cover = _check_calendar(dates, snow_cover)
    if np.nanmax(snow_cover) > 1.0 + 1e-9:
        raise ValueError("snow cover must be a fraction 0..1, not percent")
    with np.errstate(invalid="ignore"):
        return _annual(dates, snow_cover, lambda b: (b > threshold).sum(axis=0).astype(np.float64))


# ---------------------------------------------------------------- precipitation


def rx5day(dates: Sequence[date], pr: FloatArray) -> tuple[IntArray, FloatArray]:
    """Rx5day: maximum 5-day precipitation total within the year (windows inside the year).

    A window with a missing day is skipped (no gap filling).
    """
    pr = _check_calendar(dates, pr)

    def stat(b: FloatArray) -> FloatArray:
        if b.shape[0] < 5:
            return np.full(b.shape[1:], np.nan)
        c = np.concatenate([np.zeros((1, *b.shape[1:])), np.cumsum(b, axis=0)])
        win = c[5:] - c[:-5]  # NaN propagates into every window touching a gap
        with np.errstate(invalid="ignore"):
            return np.asarray(np.nanmax(np.where(np.isfinite(win), win, -np.inf), axis=0))

    years, out = _annual(dates, pr, stat)
    out[~np.isfinite(out)] = np.nan
    return years, out


def _longest_run(mask: NDArray[np.bool_]) -> FloatArray:
    run = np.zeros(mask.shape[1:])
    best = np.zeros(mask.shape[1:])
    for row in mask:
        run = (run + 1.0) * row
        np.maximum(best, run, out=best)
    return best


def cdd(dates: Sequence[date], pr: FloatArray) -> tuple[IntArray, FloatArray]:
    """CDD: longest run of days with precipitation < 1 mm within the year.

    A missing day breaks the run (it is neither dry nor wet).
    """
    pr = _check_calendar(dates, pr)
    with np.errstate(invalid="ignore"):
        return _annual(dates, pr, lambda b: _longest_run(np.isfinite(b) & (b < WET_DAY_MM)))


def _base_selection(dates: Sequence[date], base: tuple[int, int]) -> NDArray[np.bool_]:
    years = np.fromiter((d.year for d in dates), dtype=np.int64, count=len(dates))
    sel = (years >= base[0]) & (years <= base[1])
    if not sel.any():
        raise ValueError(f"base period {base} is outside the data")
    return sel


def r95ptot(
    dates: Sequence[date], pr: FloatArray, base: tuple[int, int]
) -> tuple[IntArray, FloatArray]:
    """R95pTOT: % of annual wet-day precipitation from days above the base-period 95th
    percentile of wet-day precipitation (100 * R95p / PRCPTOT).

    A year with no wet days is NaN (the share is undefined).
    """
    pr = _check_calendar(dates, pr)
    sel = _base_selection(dates, base)
    with np.errstate(invalid="ignore"):
        wet_base = np.where(pr[sel] >= WET_DAY_MM, pr[sel], np.nan)
        p95 = nan_quantile(wet_base, 0.95, axis=0) if np.isfinite(wet_base).any() else np.nan

        def stat(b: FloatArray) -> FloatArray:
            wet = np.where(b >= WET_DAY_MM, b, 0.0)
            total = np.nansum(wet, axis=0)
            heavy = np.nansum(np.where(b > p95, wet, 0.0), axis=0)
            return np.asarray(
                np.where(total > 0, 100.0 * heavy / np.where(total > 0, total, 1), np.nan)
            )

        return _annual(dates, pr, stat)


# ---------------------------------------------------------------- growing season


def _first_span_start(mask: NDArray[np.bool_], span: int) -> FloatArray:
    """Index of the first day that starts ``span`` consecutive True days (NaN if none)."""
    n = mask.shape[0]
    if n < span:
        return np.full(mask.shape[1:], np.nan)
    c = np.concatenate([np.zeros((1, *mask.shape[1:])), np.cumsum(mask, axis=0)])
    full = (c[span:] - c[:-span]) == span  # full[i]: days i..i+span-1 all True
    has = full.any(axis=0)
    first = np.argmax(full, axis=0).astype(np.float64)
    return np.where(has, first, np.nan)


def growing_season_length(
    dates: Sequence[date],
    tmean: FloatArray,
    lat: FloatArray | float | None = None,
    threshold: float = GSL_THRESHOLD_C,
    span: int = GSL_SPAN_DAYS,
) -> tuple[IntArray, FloatArray]:
    """GSL (ETCCDI): days between the first span of ``span`` days with T > ``threshold``
    and the first span of ``span`` days with T < ``threshold`` after 1 July (NH).

    No start -> 0 days; a start but no end -> the season runs to the end of the year.
    Southern Hemisphere cells (``lat < 0``) use the season year 1 July .. 30 June, reported
    under the year in which it starts; the end is searched after 1 January.
    ``threshold``/``span`` also serve the NDVI-threshold variant of section 7.
    The input is not unit-checked so that NDVI can be passed; temperatures must be in degC.
    """
    tmean = _check_calendar(dates, tmean)
    spatial = tmean.shape[1:]
    lat_arr = (
        np.zeros(spatial)
        if lat is None
        else np.broadcast_to(np.asarray(lat, dtype=np.float64), spatial)
    )
    south = lat_arr < 0

    def season(block: FloatArray, mid: int) -> FloatArray:
        n = block.shape[0]
        with np.errstate(invalid="ignore"):
            start = _first_span_start(block > threshold, span)
            end_rel = _first_span_start(block[mid:] < threshold, span)
        end = np.where(np.isfinite(end_rel), end_rel + mid, n)
        end = np.where(np.isfinite(start) & (end < start), n, end)  # end before start: open
        return np.where(np.isfinite(start), end - start, 0.0)

    blocks = year_blocks(dates)
    years = np.array([y for y, _ in blocks], dtype=np.int64)
    out = np.full((len(blocks), *spatial), np.nan)
    # Northern Hemisphere: calendar years.
    for k, (y, sl) in enumerate(blocks):
        block = tmean[sl]
        mid = (date(y, 7, 1) - dates[sl.start]).days
        if mid <= 0 or block.shape[0] < _days_in_year(y):
            continue
        val = season(block, mid)
        out[k] = np.where(~south & _valid_year(block, y), val, out[k])
    if south.any():
        first = dates[0]
        for k, y in enumerate(years):
            a = (date(int(y), 7, 1) - first).days
            b = (date(int(y) + 1, 7, 1) - first).days
            if a < 0 or b > len(dates):
                continue
            block = tmean[a:b]
            mid = (date(int(y) + 1, 1, 1) - date(int(y), 7, 1)).days
            n_valid = np.isfinite(block).sum(axis=0)
            ok = n_valid >= config.DAILY_MIN_VALID * block.shape[0]
            val = season(block, mid)
            out[k] = np.where(south & ok, val, out[k])
    return years, out


# ---------------------------------------------------------------- TX90p


def _window_samples(x: FloatArray) -> FloatArray:
    """Base-year daily values on a 365-day grid -> (n_years * (2w+1), 365, cells).

    ``x`` is (n_years, 365, cells). The +-w window wraps within each year (31 Dec borrows
    from 1 Jan of the same year), a simplification of ETCCDI's consecutive-day window.
    """
    w = TX90P_WINDOW
    shifts = [np.roll(x, -s, axis=1) for s in range(-w, w + 1)]
    stacked = np.stack(shifts, axis=1)  # (years, 2w+1, 365, cells)
    return stacked.reshape(-1, *x.shape[1:])


def _year_grid(dates: Sequence[date], data: FloatArray, years: Sequence[int]) -> FloatArray:
    """(len(years), 365, cells) on a 365-day calendar; 29 Feb is dropped."""
    doy = doy365(dates)
    yrs = np.fromiter((d.year for d in dates), dtype=np.int64, count=len(dates))
    feb29 = np.fromiter(
        ((d.month == 2 and d.day == 29) for d in dates), dtype=bool, count=len(dates)
    )
    cells = data.reshape(data.shape[0], -1)
    out = np.full((len(years), 365, cells.shape[1]), np.nan)
    for k, y in enumerate(years):
        sel = (yrs == y) & ~feb29
        out[k, doy[sel]] = cells[sel]
    return out


def tx90p(
    dates: Sequence[date],
    tmax: FloatArray,
    base: tuple[int, int],
    bootstrap_in_base: bool = True,
) -> tuple[IntArray, FloatArray]:
    """TX90p: % of days with Tmax above the base-period 90th percentile for that calendar
    day (window +-5 days).

    Years inside the base period use the out-of-base bootstrap of Zhang et al. (2005,
    J. Climate 18:1641): for base year ``i`` and every other base year ``j``, the threshold
    is estimated from the base with year ``i`` replaced by year ``j``; the exceedance rate of
    year ``i`` is averaged over the ``n - 1`` replicates. Without it, in-base years are
    compared against thresholds they helped set and the index jumps at the base edges.
    Percentiles use numpy's linear interpolation (ETCCDI uses a type-8-like estimator; the
    difference is below sampling noise for 30-year bases).
    """
    tmax = _check_calendar(dates, tmax)
    _check_celsius(tmax)
    spatial = tmax.shape[1:]
    blocks = year_blocks(dates)
    all_years = [y for y, _ in blocks]
    base_years = [y for y in all_years if base[0] <= y <= base[1]]
    if len(base_years) < 2:
        raise ValueError(f"base period {base} needs at least two years of data")

    grid = _year_grid(dates, tmax, all_years)  # (Y, 365, cells)
    pos = {y: k for k, y in enumerate(all_years)}
    bidx = [pos[y] for y in base_years]
    base_grid = grid[bidx]
    n_cells = grid.shape[2]

    def exceed(year_vals: FloatArray, thr: FloatArray) -> FloatArray:
        valid = np.isfinite(year_vals)
        with np.errstate(invalid="ignore"):
            hits = (year_vals > thr) & valid
        n = valid.sum(axis=-2)
        return np.where(n > 0, 100.0 * hits.sum(axis=-2) / np.maximum(n, 1), np.nan)

    with np.errstate(invalid="ignore"), _quiet_nan_warnings():
        thr_all = nan_quantile(_window_samples(base_grid), 0.90, axis=0)  # (365, cells)
        rates = exceed(grid, thr_all[None])  # (Y, cells)

        if bootstrap_in_base:
            nb = len(base_years)
            per_cell = nb * (nb - 1) * (2 * TX90P_WINDOW + 1) * 365 * 8
            chunk = max(1, int(CELL_CHUNK_BYTES // max(per_cell, 1)))
            for c0 in range(0, n_cells, chunk):
                cs = slice(c0, min(n_cells, c0 + chunk))
                bg = base_grid[:, :, cs]
                for i in range(nb):
                    others = [j for j in range(nb) if j != i]
                    # (nb-1 replicates, nb years, 365, cells): year i replaced by year j
                    reps = np.repeat(bg[None], nb - 1, axis=0)
                    reps[:, i] = bg[others]
                    w = TX90P_WINDOW
                    shifted = np.stack(
                        [np.roll(reps, -s, axis=2) for s in range(-w, w + 1)], axis=2
                    )  # (R, nb, 2w+1, 365, cells)
                    samples = shifted.reshape(nb - 1, -1, 365, bg.shape[2])
                    thr = nan_quantile(samples, 0.90, axis=1)  # (R, 365, cells)
                    r = exceed(bg[i][None], thr)  # (R, cells)
                    rates[bidx[i], cs] = np.nanmean(r, axis=0)

    out = np.full((len(all_years), n_cells), np.nan)
    for k, (y, sl) in enumerate(blocks):
        ok = _valid_year(tmax[sl].reshape(sl.stop - sl.start, -1), y)
        out[k] = np.where(ok, rates[k], np.nan)
    return np.array(all_years, dtype=np.int64), out.reshape(len(all_years), *spatial)


class _quiet_nan_warnings:
    """Silence 'All-NaN slice' / 'Mean of empty slice' for all-missing cells."""

    def __enter__(self) -> None:
        import warnings

        self._ctx = warnings.catch_warnings()
        self._ctx.__enter__()
        warnings.simplefilter("ignore", category=RuntimeWarning)

    def __exit__(self, *exc: object) -> None:
        self._ctx.__exit__(*exc)  # type: ignore[arg-type]
