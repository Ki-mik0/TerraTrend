"""Anomalies relative to the monthly climatology (section 4.3)."""

from __future__ import annotations

import numpy as np

from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray


def anomalies(values: FloatArray, months: IntArray, clim_mean: FloatArray) -> FloatArray:
    """``x(t) - clim(month(t))``. NaN stays NaN."""
    return values - clim_mean[months - 1]


def standardized_anomalies(
    values: FloatArray, months: IntArray, clim_mean: FloatArray, clim_std: FloatArray
) -> FloatArray:
    """``(x - clim) / std(month)``; NaN where the monthly std is 0 or undefined."""
    std = clim_std[months - 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (values - clim_mean[months - 1]) / std
    z[~np.isfinite(z)] = np.nan
    return z
