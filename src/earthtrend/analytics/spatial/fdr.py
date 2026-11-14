"""Field significance with the Benjamini-Hochberg false discovery rate (section 8.2)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config


def benjamini_hochberg(
    p: NDArray[np.float64], alpha: float = config.FDR_ALPHA
) -> tuple[NDArray[np.bool_], NDArray[np.float64], float | None]:
    """BH over the finite entries of ``p`` (any shape).

    Returns (significant mask, q-values with NaN where p is NaN, largest passing p or None).
    """
    p = np.asarray(p, dtype=np.float64)
    flat = p.ravel()
    ok = np.flatnonzero(np.isfinite(flat))
    sig = np.zeros(flat.shape, dtype=bool)
    q = np.full(flat.shape, np.nan)
    m = ok.size
    if m == 0:
        return sig.reshape(p.shape), q.reshape(p.shape), None
    order = ok[np.argsort(flat[ok], kind="stable")]
    ps = flat[order]
    ranks = np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate((ps * m / ranks)[::-1])[::-1]
    q[order] = np.minimum(q_sorted, 1.0)
    passing = np.flatnonzero(ps <= alpha * ranks / m)
    threshold = None
    if passing.size:
        k = passing[-1]
        threshold = float(ps[k])
        sig[order[: k + 1]] = True
    return sig.reshape(p.shape), q.reshape(p.shape), threshold
