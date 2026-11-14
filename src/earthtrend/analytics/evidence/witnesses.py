"""Witnesses (section 6.2): do other datasets of the same concept tell the same story?

Datasets are compared on their common period through the series of differences
``d(t) = x1(t) - x2(t)`` of monthly anomalies: shared weather noise cancels, so a
significant trend in ``d`` means the datasets really disagree on the rate of change.
"""

from __future__ import annotations

from datetime import date
from itertools import combinations

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.models import (
    ItemStatus,
    RegionalSeries,
    WitnessDataset,
    WitnessesResult,
    WitnessPair,
)
from earthtrend.analytics.preprocess.aggregate import FloatArray, decimal_year
from earthtrend.analytics.preprocess.anomalies import anomalies
from earthtrend.analytics.preprocess.climatology import monthly_climatology
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.ols import ols_ar1
from earthtrend.analytics.trend.sen import sen_slope


def _anomalies_on(
    s: RegionalSeries, months_index: dict[tuple[int, int], int], n: int, log: bool
) -> FloatArray:
    out = np.full(n, np.nan)
    for d, v in zip(s.dates, s.values, strict=True):
        k = months_index.get((d.year, d.month))
        if k is not None and v is not None:
            out[k] = np.log(v) if log else v
    if log:
        out[~np.isfinite(out)] = np.nan
    return out


def compare_witnesses(
    primary: RegionalSeries,
    witnesses: list[RegionalSeries],
    alpha: float = config.ALPHA,
) -> WitnessesResult | None:
    """None when there are no witnesses (status ``na``)."""
    if not witnesses:
        return None
    series = [primary, *witnesses]
    start = max(s.dates[0] for s in series)
    end = min(s.dates[-1] for s in series)
    if start >= end:
        return WitnessesResult(common_period=None, datasets=[], pairs=[])
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    index = {ym: i for i, ym in enumerate(months)}
    years = np.array([ym[0] for ym in months], dtype=np.int64)
    mon = np.array([ym[1] for ym in months], dtype=np.int64)
    t = decimal_year(years, mon)
    log = primary.meta.transform == "log"

    anoms: list[FloatArray] = []
    datasets: list[WitnessDataset] = []
    for s in series:
        x = _anomalies_on(s, index, len(months), log)
        clim, _ = monthly_climatology(x, years, mon)
        a = anomalies(x, mon, clim)
        anoms.append(a)
        mk = mk_ar1(a)
        sen = sen_slope(t, a, mk.var_s, alpha) if mk else None
        datasets.append(
            WitnessDataset(
                dataset_id=s.meta.dataset_id,
                slope_per_decade=sen.slope * 10 if sen else None,
                p_mk=mk.p_value if mk else None,
                significant=bool(mk and mk.p_value < alpha),
            )
        )

    pairs: list[WitnessPair] = []
    for (i, a), (j, b) in combinations(enumerate(anoms), 2):
        d = a - b
        ols = ols_ar1(t, d)
        mk = mk_ar1(d)
        diverge = bool(ols and mk and ols.p_value < alpha and mk.p_value < alpha)
        pairs.append(
            WitnessPair(
                a=datasets[i].dataset_id,
                b=datasets[j].dataset_id,
                diff_slope_per_decade=ols.slope * 10 if ols else None,
                p_mk=mk.p_value if mk else None,
                p_ols=ols.p_value if ols else None,
                diverge=diverge,
            )
        )
    first, last = months[0], months[-1]
    return WitnessesResult(
        common_period=(date(first[0], first[1], 1), date(last[0], last[1], 1)),
        datasets=datasets,
        pairs=pairs,
    )


def witnesses_status(res: WitnessesResult | None) -> ItemStatus:
    if res is None or len(res.datasets) < 2:
        return "na"
    signs = {np.sign(d.slope_per_decade) for d in res.datasets if d.slope_per_decade}
    if len(signs) != 1:
        return "fail"
    if all(d.significant for d in res.datasets) and not any(p.diverge for p in res.pairs):
        return "pass"
    return "partial"
