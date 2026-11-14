"""``analyze_grid``: monthly field -> ``GridTrendProduct`` (section 8, stage A3).

The product holds per-cell NumPy arrays (for map tiles, rendered by the backend) and a
JSON ``GridSummary`` (split, zones, counts). ``ai_class`` / ``ai_step_prob`` arrive with M1.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config
from earthtrend.analytics.models import GridSummary
from earthtrend.analytics.preprocess.aggregate import split_dates
from earthtrend.analytics.regional.weights import area_weights
from earthtrend.analytics.spatial.fdr import benjamini_hochberg
from earthtrend.analytics.spatial.grid_trend import GridTrendFields, grid_trends
from earthtrend.analytics.spatial.split import split_region
from earthtrend.analytics.spatial.zones import find_zones


@dataclass(frozen=True)
class GridTrendProduct:
    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    fields: GridTrendFields
    p_combined: NDArray[np.float64]  # max(p_ols, p_mk): both tests must agree
    q_fdr: NDArray[np.float64]
    sig_fdr: NDArray[np.bool_]
    zone_id: NDArray[np.int64]  # 0 = no zone; ids match summary.zones
    summary: GridSummary
    # M1 TrendNet per cell (advisory map layer "type of change"): class index into
    # training.trendnet.data.CLASSES (-1 = no data) and max monthly step probability.
    ai_class: NDArray[np.int64] | None = None
    ai_step_prob: NDArray[np.float64] | None = None


def analyze_grid(
    cube: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    dates: Sequence[date],
    region_mask: NDArray[np.floating] | NDArray[np.bool_] | None = None,
    domain_mask: NDArray[np.bool_] | None = None,
    baseline: tuple[int, int] | None = None,
    alpha: float = config.ALPHA,
    fdr_alpha: float = config.FDR_ALPHA,
    ai: bool = False,
) -> GridTrendProduct:
    """Trends per cell, FDR, region split and zones.

    ``region_mask`` (bool or 0..1 fraction) restricts the analysis to a region; FDR is then
    applied within the region only. ``domain_mask`` (land/ocean) removes cells entirely.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    shape = (lat.size, lon.size)
    frac = np.ones(shape) if region_mask is None else np.asarray(region_mask, dtype=np.float64)
    if frac.shape != shape:
        raise ValueError(f"region_mask shape {frac.shape} != (lat, lon) {shape}")
    cells = frac > 0
    if domain_mask is not None:
        cells &= np.asarray(domain_mask, dtype=bool)

    f = grid_trends(cube, dates, cells, baseline, alpha)
    p = np.fmax(f.p_ols, f.p_mk)
    p = np.where(f.valid, np.where(np.isnan(f.p_ols) | np.isnan(f.p_mk), np.nan, p), np.nan)
    sig, q, threshold = benjamini_hochberg(p, fdr_alpha)

    weights = area_weights(lat, lon, frac) * f.valid
    split = split_region(sig, f.slope, weights)
    zones, zone_id = find_zones(sig, f.slope, lat, lon, f.valid, weights=frac)

    w_sum = float(weights.sum())
    mean_slope = float(np.nansum(weights * np.nan_to_num(f.slope)) / w_sum) if w_sum > 0 else None
    summary = GridSummary(
        n_cells_valid=int(f.valid.sum()),
        n_cells_significant=int(sig.sum()),
        fdr_alpha=fdr_alpha,
        p_threshold=threshold,
        area_weighted_mean_slope_per_decade=mean_slope,
        split=split,
        zones=zones,
    )
    ai_class = ai_step = None
    if ai:
        ai_class, ai_step = _ai_layer(cube, dates, f.valid)
    return GridTrendProduct(
        lat=lat,
        lon=lon,
        fields=f,
        p_combined=p,
        q_fdr=q,
        sig_fdr=sig,
        zone_id=zone_id,
        summary=summary,
        ai_class=ai_class,
        ai_step_prob=ai_step,
    )


def _ai_layer(
    cube: NDArray[np.float64], dates: Sequence[date], valid: NDArray[np.bool_]
) -> tuple[NDArray[np.int64] | None, NDArray[np.float64] | None]:
    """M1 class per valid cell from monthly anomalies; (None, None) without a model."""
    from earthtrend.analytics.ml.trendnet import classify_grid

    years, months = split_dates(dates)
    cube = np.asarray(cube, dtype=np.float64)
    nt = cube.shape[0]
    flat = cube.reshape(nt, -1)[:, valid.ravel()]
    anom = np.empty_like(flat)
    for m in range(1, 13):
        rows = months == m
        anom[rows] = flat[rows] - np.nanmean(flat[rows], axis=0)
    res = classify_grid(anom.T, months)
    if res is None:
        return None, None
    cls = np.full(valid.size, -1, dtype=np.int64)
    step = np.full(valid.size, np.nan)
    cls[valid.ravel()], step[valid.ravel()] = res
    return cls.reshape(valid.shape), step.reshape(valid.shape)
