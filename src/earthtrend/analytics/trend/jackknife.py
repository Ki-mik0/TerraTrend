"""Influence of single years (section 5.9): Sen + MK on annual means, leaving out one year.

Annual means keep this cheap (n ~ 45 instead of ~540 months), so the whole case still
fits the 300 ms budget. Influence is only judged when the full-period trend is significant:
for a flat series the relative change of a ~0 slope is meaningless.
"""

from __future__ import annotations

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.models import JackknifeResult
from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.sen import sen_slope

REL_CHANGE_LIMIT = 0.30


def _sen_mk(years: FloatArray, values: FloatArray, alpha: float) -> tuple[float, float] | None:
    mk = mk_ar1(values)
    if mk is None:
        return None
    sen = sen_slope(years, values, mk.var_s, alpha)
    if sen is None:
        return None
    return sen.slope * 10, mk.p_value


def jackknife(
    years: IntArray, annual: FloatArray, alpha: float = config.ALPHA
) -> JackknifeResult | None:
    """Leave-one-year-out influence of single years on the Sen slope and MK p-value.

    For each year k: slope_(-k) = Sen slope without year k. Relative change =
    |slope_(-k) - slope| / |slope|. A year is influential if the full trend is significant
    and max relative change > REL_CHANGE_LIMIT (0.30), or dropping it makes p >= alpha.
    Sen slope after Sen (1968); MK variance with AR(1) correction (Hamed & Rao 1998).
    """
    yf = years.astype(np.float64)
    full = _sen_mk(yf, annual, alpha)
    if full is None:
        return None
    full_slope, full_p = full
    out_years: list[int] = []
    slopes: list[float | None] = []
    ps: list[float | None] = []
    for k in np.flatnonzero(np.isfinite(annual)):
        keep = np.ones(annual.size, dtype=bool)
        keep[k] = False
        r = _sen_mk(yf[keep], annual[keep], alpha)
        out_years.append(int(years[k]))
        slopes.append(None if r is None else r[0])
        ps.append(None if r is None else r[1])

    significant = full_p < alpha
    rel = [
        abs(s - full_slope) / abs(full_slope) if s is not None and full_slope != 0 else 0.0
        for s in slopes
    ]
    max_rel = max(rel) if rel else 0.0
    most = out_years[int(np.argmax(rel))] if rel else None
    lost = [(p, y) for p, y in zip(ps, out_years, strict=True) if p is not None and p >= alpha]
    lost_year = max(lost)[1] if (significant and lost) else None
    influential = significant and (max_rel > REL_CHANGE_LIMIT or lost_year is not None)
    return JackknifeResult(
        years=out_years,
        slope_per_decade=slopes,
        p_mk=ps,
        full_slope_per_decade=full_slope,
        full_p_mk=full_p,
        max_rel_change=max_rel,
        most_influential_year=most,
        significance_lost_year=lost_year,
        influential=influential,
    )
