"""Zones: connected patches of significant trend of one sign (section 8.4).

8-connectivity; on a global grid the longitude axis is cyclic (patches crossing the
antimeridian are one zone). Zones with fewer than 3 cells or < 0.5% of the analysed
area are dropped.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from earthtrend.analytics import config
from earthtrend.analytics.models import Zone

EIGHT = np.ones((3, 3), dtype=bool)


def _spacing(axis: NDArray[np.float64]) -> float:
    return float(np.median(np.abs(np.diff(axis)))) if axis.size > 1 else 1.0


def is_cyclic(lon: NDArray[np.float64]) -> bool:
    """True when the longitudes cover the whole circle."""
    return lon.size > 2 and abs(_spacing(lon) * lon.size - 360.0) < _spacing(lon) / 2


def cell_area_km2(lat: NDArray[np.float64], lon: NDArray[np.float64]) -> NDArray[np.float64]:
    """Area of each cell of a regular grid, shape (lat, lon)."""
    dlat, dlon = math.radians(_spacing(lat)), math.radians(_spacing(lon))
    rows = config.EARTH_RADIUS_KM**2 * dlat * dlon * np.clip(np.cos(np.deg2rad(lat)), 0, None)
    return np.repeat(rows[:, None], lon.size, axis=1)


def _label_cyclic(mask: NDArray[np.bool_], cyclic: bool) -> tuple[NDArray[np.int64], int]:
    labels, n = ndimage.label(mask, structure=EIGHT)
    labels = labels.astype(np.int64)
    if not cyclic or n < 2:
        return labels, n
    parent = list(range(n + 1))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    nlat = mask.shape[0]
    for r in range(nlat):
        a = labels[r, 0]
        if not a:
            continue
        for dr in (-1, 0, 1):
            rr = r + dr
            if 0 <= rr < nlat and labels[rr, -1]:
                ra, rb = find(int(a)), find(int(labels[rr, -1]))
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(k) for k in range(n + 1)])
    merged = roots[labels]
    uniq = np.unique(merged[merged > 0])
    remap = np.zeros(n + 1, dtype=np.int64)
    remap[uniq] = np.arange(1, uniq.size + 1)
    return remap[merged], int(uniq.size)


def find_zones(
    sig: NDArray[np.bool_],
    slope: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    analysed: NDArray[np.bool_],
    weights: NDArray[np.float64] | None = None,
) -> tuple[list[Zone], NDArray[np.int64]]:
    """Return zones (largest first) and a (lat, lon) label map (0 = no zone).

    ``analysed`` marks cells that had a valid trend (the area base for the 0.5% rule).
    ``weights`` (e.g. fraction of the cell inside the region) scale cell areas; default 1.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    area = cell_area_km2(lat, lon) * (1.0 if weights is None else weights)
    total = float(area[analysed].sum())
    cyclic = is_cyclic(lon)
    lat2 = np.repeat(lat[:, None], lon.size, axis=1)
    lon2 = np.repeat(lon[None, :], lat.size, axis=0)

    found: list[tuple[Zone, NDArray[np.bool_]]] = []
    finite = np.isfinite(slope)
    for sign in (1, -1):
        mask = sig & finite & ((slope > 0) if sign > 0 else (slope < 0))
        labels, n = _label_cyclic(mask, cyclic)
        for k in range(1, n + 1):
            cells = labels == k
            a = area[cells]
            a_sum = float(a.sum())
            n_cells = int(cells.sum())
            if (
                n_cells < config.ZONE_MIN_CELLS
                or total <= 0
                or a_sum / total < config.ZONE_MIN_AREA_SHARE
            ):
                continue
            lam = np.deg2rad(lon2[cells])
            c_lon = math.degrees(
                math.atan2(float((a * np.sin(lam)).sum()), float((a * np.cos(lam)).sum()))
            )
            zone = Zone(
                id=0,
                sign=sign,
                n_cells=n_cells,
                area_km2=a_sum,
                area_share=a_sum / total,
                mean_slope_per_decade=float((a * slope[cells]).sum() / a_sum),
                centroid=(float((a * lat2[cells]).sum() / a_sum), c_lon),
                bbox=(
                    float(lat2[cells].min()),
                    float(lon2[cells].min()),
                    float(lat2[cells].max()),
                    float(lon2[cells].max()),
                ),
            )
            found.append((zone, cells))

    found.sort(key=lambda zc: zc[0].area_km2, reverse=True)
    label_map = np.zeros(sig.shape, dtype=np.int64)
    zones: list[Zone] = []
    for zone_id, (zone, cells) in enumerate(found, start=1):
        label_map[cells] = zone_id
        zones.append(zone.model_copy(update={"id": zone_id}))
    return zones, label_map
