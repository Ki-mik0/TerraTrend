"""Area weights for regional means (section 4.4): ``cos(lat) x fraction_in_region x stable``."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def area_weights(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    region_mask: NDArray[np.floating] | NDArray[np.bool_],
    stable: NDArray[np.bool_] | None = None,
) -> NDArray[np.float64]:
    """Return weights of shape (lat, lon).

    ``region_mask`` is a boolean mask or the fraction (0..1) of each cell inside the region.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    frac = np.asarray(region_mask, dtype=np.float64)
    if frac.shape != (lat.size, lon.size):
        raise ValueError(f"region_mask shape {frac.shape} != (lat, lon) {(lat.size, lon.size)}")
    if np.any((frac < 0) | (frac > 1)):
        raise ValueError("region_mask fractions must lie in [0, 1]")
    w = np.cos(np.deg2rad(lat))[:, None] * frac
    w = np.clip(w, 0.0, None)  # cos is ~-0 at the poles
    if stable is not None:
        w = w * np.asarray(stable, dtype=np.float64)
    return w
