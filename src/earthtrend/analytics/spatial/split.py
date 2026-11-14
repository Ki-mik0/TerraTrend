"""Region split: how much area warms vs cools significantly (section 8.3)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config
from earthtrend.analytics.models import SplitResult


def split_region(
    sig: NDArray[np.bool_],
    slope: NDArray[np.float64],
    weights: NDArray[np.float64],
    min_share: float = config.SPLIT_MIN_SHARE,
) -> SplitResult:
    """Shares are weighted by ``weights`` over cells with a finite slope."""
    valid = np.isfinite(slope) & (weights > 0)
    w = np.where(valid, weights, 0.0)
    total = w.sum()
    if total <= 0:
        return SplitResult(sig_pos=0.0, sig_neg=0.0, nonsig=1.0, split_flag=False)
    pos = float(w[sig & valid & (slope > 0)].sum() / total)
    neg = float(w[sig & valid & (slope < 0)].sum() / total)
    return SplitResult(
        sig_pos=pos,
        sig_neg=neg,
        nonsig=max(0.0, 1.0 - pos - neg),
        split_flag=pos >= min_share and neg >= min_share,
    )
