"""Monthly climatology over a baseline period (section 4.3)."""

from __future__ import annotations

import warnings

import numpy as np

from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray


def _in_baseline(years: IntArray, baseline: tuple[int, int] | None) -> np.ndarray:
    if baseline is None:
        return np.ones(years.shape, dtype=bool)
    return (years >= baseline[0]) & (years <= baseline[1])


def monthly_climatology(
    values: FloatArray,
    years: IntArray,
    months: IntArray,
    baseline: tuple[int, int] | None = None,
) -> tuple[FloatArray, FloatArray]:
    """Return (mean, std) per calendar month, shape (12,). Index 0 is January.

    Months with no valid value in the baseline get NaN.
    """
    sel = _in_baseline(years, baseline)
    mean = np.full(12, np.nan)
    std = np.full(12, np.nan)
    for m in range(1, 13):
        v = values[sel & (months == m)]
        v = v[np.isfinite(v)]
        if v.size:
            mean[m - 1] = v.mean()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                std[m - 1] = v.std(ddof=1) if v.size > 1 else np.nan
    return mean, std
