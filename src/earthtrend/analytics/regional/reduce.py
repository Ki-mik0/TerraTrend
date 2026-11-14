"""Area-weighted regional mean with the stable mask (section 4.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config
from earthtrend.analytics.models import RegionalSeries, SeriesMeta
from earthtrend.analytics.preprocess.stable_mask import stable_mask
from earthtrend.analytics.regional.weights import area_weights


def weighted_mean(
    cube: NDArray[np.float64],
    weights: NDArray[np.float64],
    min_coverage: float = config.MONTH_MIN_COVERAGE,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Per time step: weighted mean over valid cells and coverage (share of total weight).

    A step whose coverage is below ``min_coverage`` becomes NaN.
    """
    total = weights.sum()
    if total <= 0:
        raise ValueError("region has no weight (empty mask or no stable cells)")
    valid = np.isfinite(cube)
    w = np.where(valid, weights[None, :, :], 0.0)
    wsum = w.sum(axis=(1, 2))
    num = np.where(valid, cube, 0.0) * w
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = num.sum(axis=(1, 2)) / wsum
    coverage = wsum / total
    mean[(coverage < min_coverage) | (wsum == 0)] = np.nan
    return mean, coverage


def regional_series(
    cube: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    region_mask: NDArray[np.floating] | NDArray[np.bool_],
    dates: Sequence[date],
    meta: SeriesMeta,
    use_stable_mask: bool = True,
) -> RegionalSeries:
    """Monthly gridded field (time, lat, lon) -> regional mean series.

    ``use_stable_mask=False`` averages all valid cells each month, as Giovanni does; use it
    only for the Giovanni comparison (section 13.4).
    """
    cube = np.asarray(cube, dtype=np.float64)
    if cube.shape[0] != len(dates):
        raise ValueError("cube time axis and dates differ in length")
    stable = stable_mask(cube) if use_stable_mask else np.ones(cube.shape[1:], dtype=bool)
    w_region = area_weights(lat, lon, region_mask)
    w = area_weights(lat, lon, region_mask, stable)
    region_total = w_region.sum()
    if region_total <= 0:
        raise ValueError("region mask does not overlap the grid")
    stable_fraction = float(w.sum() / region_total)
    mean, coverage = weighted_mean(cube, w)
    return RegionalSeries(
        meta=meta,
        dates=[date(d.year, d.month, 1) for d in dates],
        values=[None if not np.isfinite(v) else float(v) for v in mean],
        coverage=[float(c) for c in coverage],
        stable_fraction=min(1.0, stable_fraction),
    )
