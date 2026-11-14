"""Stable mask: grid cells valid in most of the analysis period (section 4.4).

Without it, cells entering or leaving the average over time create a fake trend.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config


def stable_mask(
    cube: NDArray[np.float64], min_valid: float = config.STABLE_MASK_MIN_VALID
) -> NDArray[np.bool_]:
    """``cube`` has shape (time, lat, lon). Returns a (lat, lon) boolean mask."""
    if cube.ndim != 3:
        raise ValueError("cube must have shape (time, lat, lon)")
    valid_share = np.isfinite(cube).mean(axis=0)
    return np.asarray(valid_share >= min_valid)
