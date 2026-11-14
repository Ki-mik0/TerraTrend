"""Seasonal Mann-Kendall (Hirsch et al. 1982) on raw monthly values (section 5.2).

S and Var(S) are summed over the 12 calendar months; each month is one value per year.
No serial-correlation correction across years (annual sampling of one month is close to
independent for most variables).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from earthtrend.analytics.preprocess.aggregate import FloatArray, IntArray
from earthtrend.analytics.trend.mann_kendall import _s_statistic, _variance_independent


def seasonal_mk(values: FloatArray, months: IntArray) -> tuple[float, float] | None:
    """Return (p_value, z) or None when no month has >= 4 values."""
    s_total = 0.0
    var_total = 0.0
    for m in range(1, 13):
        v = values[(months == m) & np.isfinite(values)]
        if v.size < 4:
            continue
        s_total += _s_statistic(v)
        var_total += _variance_independent(v)
    if var_total <= 0:
        return None
    z = (s_total - math.copysign(1.0, s_total)) / math.sqrt(var_total) if s_total else 0.0
    return float(2 * stats.norm.sf(abs(z))), z
