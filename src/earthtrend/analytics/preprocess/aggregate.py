"""Time axis helpers and monthly -> seasonal / annual aggregation (section 4.1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def split_dates(dates: Sequence[date]) -> tuple[IntArray, IntArray]:
    """Return (years, months) integer arrays."""
    years = np.fromiter((d.year for d in dates), dtype=np.int64, count=len(dates))
    months = np.fromiter((d.month for d in dates), dtype=np.int64, count=len(dates))
    return years, months


def decimal_year(years: IntArray, months: IntArray) -> FloatArray:
    """Mid-month decimal year: 1980-01 -> 1980.0417."""
    return years.astype(np.float64) + (months.astype(np.float64) - 0.5) / 12.0


def _month_table(
    values: FloatArray, years: IntArray, months: IntArray
) -> dict[tuple[int, int], float]:
    return {
        (int(y), int(m)): float(v)
        for y, m, v in zip(years, months, values, strict=True)
        if np.isfinite(v)
    }


def seasonal_means(
    values: FloatArray, years: IntArray, months: IntArray, season: str
) -> tuple[IntArray, FloatArray]:
    """Mean of the 3 months of ``season`` per year; valid only if all 3 months are valid.

    DJF is tied to the year of January: Dec 1999 + Jan/Feb 2000 -> DJF 2000.
    """
    season_months = config.SEASON_MONTHS[season]
    table = _month_table(values, years, months)
    out_years: list[int] = []
    out_vals: list[float] = []
    for y in range(int(years.min()), int(years.max()) + 1):
        keys = [(y - 1 if (season == "DJF" and m == 12) else y, m) for m in season_months]
        # Only emit years whose season lies inside the record.
        if not all((years == k[0]).any() for k in keys):
            continue
        vals = [table[k] for k in keys if k in table]
        out_years.append(y)
        out_vals.append(float(np.mean(vals)) if len(vals) == len(keys) else np.nan)
    return np.asarray(out_years, dtype=np.int64), np.asarray(out_vals, dtype=np.float64)


def annual_means(
    values: FloatArray, years: IntArray, months: IntArray
) -> tuple[IntArray, FloatArray]:
    """Calendar-year mean; valid with >= 10 valid months and no season missing 2+ months."""
    table = _month_table(values, years, months)
    out_years = np.unique(years)
    out_vals = np.full(out_years.shape, np.nan)
    for i, y in enumerate(out_years):
        vals = [table.get((int(y), m)) for m in range(1, 13)]
        valid = [v for v in vals if v is not None]
        if len(valid) < config.ANNUAL_MIN_MONTHS:
            continue
        missing_by_season = [
            sum(table.get((int(y), m)) is None for m in config.SEASON_MONTHS[s])
            for s in config.SEASON_MONTHS
        ]
        if max(missing_by_season) >= 2:
            continue
        out_vals[i] = float(np.mean(valid))
    return out_years, out_vals


def daily_to_monthly(
    dates: Sequence[date],
    values: Sequence[float | None],
    how: str = "mean",
    min_valid: float = config.DAILY_MIN_VALID,
) -> tuple[list[date], list[float | None]]:
    """Daily -> monthly (section 4.1): a month is valid with >= 80% of its days present.

    ``how``: ``mean`` (temperature), ``sum`` (precipitation; scaled up from the valid days so
    a month with a few missing days is not biased low), ``max`` or ``min``.
    """
    import calendar

    buckets: dict[tuple[int, int], list[float]] = {}
    for d, v in zip(dates, values, strict=True):
        key = (d.year, d.month)
        bucket = buckets.setdefault(key, [])
        if v is not None and np.isfinite(v):
            bucket.append(float(v))
    out_dates: list[date] = []
    out_vals: list[float | None] = []
    for y, m in sorted(buckets):
        vals = buckets[(y, m)]
        n_days = calendar.monthrange(y, m)[1]
        out_dates.append(date(y, m, 1))
        if len(vals) < min_valid * n_days:
            out_vals.append(None)
            continue
        arr = np.asarray(vals)
        if how == "mean":
            out_vals.append(float(arr.mean()))
        elif how == "sum":
            out_vals.append(float(arr.sum() * n_days / len(vals)))
        elif how == "max":
            out_vals.append(float(arr.max()))
        elif how == "min":
            out_vals.append(float(arr.min()))
        else:
            raise ValueError(f"unknown aggregation {how!r}")
    return out_dates, out_vals
