"""Robust STL decomposition, period 12 (section 4.3). Visualization only: never feeds a test.

Gaps are interpolated for the decomposition and masked again in the output.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from earthtrend.analytics.models import StlResult
from earthtrend.analytics.preprocess.aggregate import FloatArray


def stl_decompose(dates: list[date], values: FloatArray, period: int = 12) -> StlResult | None:
    """Robust STL (Cleveland et al., 1990; period 12) of the monthly series, for charts only
    (section 4.3). Gaps are linearly interpolated for the fit and returned as None; None
    with fewer than 2 * period + 1 valid months.
    """
    from statsmodels.tsa.seasonal import STL

    ok = np.isfinite(values)
    if ok.sum() < 2 * period + 1:
        return None
    filled = np.interp(np.arange(values.size), np.flatnonzero(ok), values[ok])
    res = STL(filled, period=period, robust=True).fit()

    def _mask(x: np.ndarray) -> list[float | None]:
        return [float(v) if k else None for v, k in zip(x, ok, strict=True)]

    return StlResult(
        dates=dates,
        trend=_mask(np.asarray(res.trend)),
        seasonal=_mask(np.asarray(res.seasonal)),
        resid=_mask(np.asarray(res.resid)),
    )
