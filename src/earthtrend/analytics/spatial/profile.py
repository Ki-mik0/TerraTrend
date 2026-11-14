"""Vertical profile of trends on pressure levels (docs/PLAN_ANALYTICS.md section 8.6).

Each level's regional series goes through ``analyze_series``. Levels are tested together
with Benjamini-Hochberg (a profile of ~10-20 levels is a family of tests). The level p is
``max(p_ols_annual, p_mk)``: a level is significant only when both decision tests agree,
as for grid cells (section 8.2). The tropopause is marked and the pattern
``troposphere_warming_stratosphere_cooling`` is set when a significant warming level lies
below it and a significant cooling level above it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.models import AnalysisOptions, RegionalSeries, TrendResult
from earthtrend.analytics.spatial.fdr import benjamini_hochberg

PATTERN_T_PROFILE = "troposphere_warming_stratosphere_cooling"


class LevelTrend(BaseModel):
    level_hpa: float
    slope_per_decade: float | None
    ci95: tuple[float, float] | None
    p_mk: float | None
    p_ols: float | None
    p_level: float | None  # max(p_ols, p_mk), the p used for FDR
    q_value: float | None
    significant: bool  # BH over levels at config.FDR_ALPHA
    above_tropopause: bool
    verdict: str


class VerticalProfile(BaseModel):
    variable_id: str
    region_id: str
    tropopause_hpa: float
    tropopause_source: Literal["given", "latitude"]
    fdr_alpha: float
    levels: list[LevelTrend]  # ordered from the surface (high pressure) upward
    sign_change_hpa: float | None  # lowest level where the slope sign flips
    patterns: list[str]
    results: list[TrendResult]  # full results, same order as ``levels``


def climatological_tropopause_hpa(lat: float) -> float:
    """Rough zonal-mean tropopause: ~100 hPa in the tropics, ~250 in mid-latitudes, ~300
    near the poles (e.g. Hoinka 1998, Mon. Wea. Rev. 126). Only a fallback marker."""
    a = abs(lat)
    if a < 30:
        return 100.0
    if a < 60:
        return 250.0
    return 300.0


def vertical_profile(
    levels_hpa: Sequence[float],
    series: Sequence[RegionalSeries],
    options: AnalysisOptions | None = None,
    *,
    tropopause_hpa: float | None = None,
    lat: float | None = None,
    fdr_alpha: float = config.FDR_ALPHA,
) -> VerticalProfile:
    """``series[k]`` is the regional series at ``levels_hpa[k]`` (same variable and region).

    Give ``tropopause_hpa`` (e.g. from MERRA-2 TROPPB) or ``lat`` for the fallback.
    """
    if len(levels_hpa) != len(series) or not series:
        raise ValueError("need one series per level")
    if len(set(levels_hpa)) != len(levels_hpa):
        raise ValueError("levels must be unique")
    metas = {(s.meta.variable_id, s.meta.region_id) for s in series}
    if len(metas) != 1:
        raise ValueError("all levels must share variable_id and region_id")
    if tropopause_hpa is None:
        if lat is None:
            raise ValueError("give tropopause_hpa or lat")
        trop = climatological_tropopause_hpa(lat)
        source: Literal["given", "latitude"] = "latitude"
    else:
        trop, source = float(tropopause_hpa), "given"

    opts = (options or AnalysisOptions()).model_copy(
        update={"seasonal_breakdown": False, "nonlinear": False}
    )
    order = [int(i) for i in np.argsort(-np.asarray(levels_hpa, dtype=np.float64))]  # surface first
    lv = [float(levels_hpa[i]) for i in order]
    results = [analyze_series(series[i], opts) for i in order]

    def p_of(r: TrendResult, method: str) -> float | None:
        t = r.test(method)
        return None if t is None else t.p_value

    p_ols = [p_of(r, "ols_ar1_annual") or p_of(r, "ols_ar1") for r in results]
    p_mk = [p_of(r, "mk_ar1") for r in results]
    p_lev = np.array(
        [
            max(a, b) if a is not None and b is not None else np.nan
            for a, b in zip(p_ols, p_mk, strict=True)
        ]
    )
    sig, q, _ = benjamini_hochberg(p_lev, fdr_alpha)

    rows: list[LevelTrend] = []
    for k, r in enumerate(results):
        rows.append(
            LevelTrend(
                level_hpa=lv[k],
                slope_per_decade=r.primary_slope_per_decade,
                ci95=r.primary_ci95,
                p_mk=p_mk[k],
                p_ols=p_ols[k],
                p_level=None if np.isnan(p_lev[k]) else float(p_lev[k]),
                q_value=None if np.isnan(q[k]) else float(q[k]),
                significant=bool(sig[k]),
                above_tropopause=lv[k] < trop,
                verdict=r.verdict.code,
            )
        )

    sign_change = None
    signs = [np.sign(r.slope_per_decade or 0.0) for r in rows]
    for k in range(1, len(rows)):
        if signs[k] != 0 and signs[k - 1] != 0 and signs[k] != signs[k - 1]:
            sign_change = rows[k].level_hpa
            break

    patterns: list[str] = []
    warm_below = any(
        r.significant and not r.above_tropopause and (r.slope_per_decade or 0) > 0 for r in rows
    )
    cool_above = any(
        r.significant and r.above_tropopause and (r.slope_per_decade or 0) < 0 for r in rows
    )
    if warm_below and cool_above:
        patterns.append(PATTERN_T_PROFILE)

    variable_id, region_id = next(iter(metas))
    return VerticalProfile(
        variable_id=variable_id,
        region_id=region_id,
        tropopause_hpa=trop,
        tropopause_source=source,
        fdr_alpha=fdr_alpha,
        levels=rows,
        sign_change_hpa=sign_change,
        patterns=patterns,
        results=results,
    )
