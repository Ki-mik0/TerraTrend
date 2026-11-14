"""Trend of each calendar month (section 5.8): 12 annual series, Sen + MK, FDR over 12."""

from __future__ import annotations

import numpy as np

from earthtrend.analytics.models import MonthTrend
from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray
from earthtrend.analytics.spatial.fdr import benjamini_hochberg
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.sen import sen_slope


def monthly_trends(
    values: FloatArray, years: IntArray, months: IntArray, alpha: float = 0.05
) -> list[MonthTrend]:
    """Trend of each calendar month: 12 annual series, Sen slope + MK test, BH-FDR over 12.

    Slope per decade = 10 * median((y_j - y_i) / (t_j - t_i)) (Sen 1968); significance from
    q-values of the Benjamini & Hochberg (1995) procedure over the 12 monthly p-values.
    """
    rows: list[tuple[int, float | None, tuple[float, float] | None, float | None, int]] = []
    for m in range(1, 13):
        sel = (months == m) & np.isfinite(values)
        yv, vv = years[sel].astype(np.float64), values[sel]
        mk = mk_ar1(vv)
        sen = sen_slope(yv, vv, mk.var_s, alpha) if mk else None
        rows.append(
            (
                m,
                sen.slope * 10 if sen else None,
                (sen.ci95[0] * 10, sen.ci95[1] * 10) if sen else None,
                mk.p_value if mk else None,
                int(sel.sum()),
            )
        )
    p = np.array([np.nan if r[3] is None else r[3] for r in rows])
    sig, q, _ = benjamini_hochberg(p, alpha)
    return [
        MonthTrend(
            month=m,
            slope_per_decade=s,
            ci95=ci,
            p_mk=pv,
            q_value=None if np.isnan(q[i]) else float(q[i]),
            significant=bool(sig[i]),
            n_years=n,
        )
        for i, (m, s, ci, pv, n) in enumerate(rows)
    ]
