"""Years of data needed to detect a trend (section 5.7, Weatherhead et al. 1998)."""

from __future__ import annotations

import math


def years_to_detect(slope_per_year: float, sigma_noise: float, phi: float) -> float | None:
    """``n* = [(3.3 sigma_N / |omega|) * sqrt((1 + phi) / (1 - phi))]^(2/3)`` in years.

    ``sigma_noise`` and ``phi`` describe the monthly noise (residual std, lag-1 autocorrelation).
    Returns None when the trend is ~0.
    """
    if not math.isfinite(slope_per_year) or abs(slope_per_year) < 1e-12 or sigma_noise <= 0:
        return None
    phi = min(max(phi, 0.0), 0.99)
    ratio = 3.3 * sigma_noise / abs(slope_per_year)
    return float((ratio * math.sqrt((1 + phi) / (1 - phi))) ** (2 / 3))
