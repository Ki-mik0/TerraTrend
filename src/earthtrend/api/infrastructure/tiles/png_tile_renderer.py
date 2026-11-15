"""Render a 256×256 PNG tile from grid arrays: Web Mercator pixels, nearest grid cell, colour LUT.

Hatching of significance is drawn by the frontend; here a non-significant cell is only fainter,
or fully transparent with `significant_only`.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from earthtrend.api.application.tiles.ports import GridArrays
from earthtrend.api.domain.tiles.model import AI_CLASSES, TILE_SIZE, GridProduct, TileRequest

_ANCHORS = {
    # ColorBrewer RdBu and PuOr (colour-blind safe), low to high.
    "rdbu": ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"],
    "puor": ["#542788", "#998ec3", "#d8daeb", "#f7f7f7", "#fee0b6", "#f1a340", "#b35806"],
    # cividis: perceptually uniform and readable with any colour vision.
    "cividis": ["#00204d", "#31446b", "#666970", "#958f78", "#cbba69", "#ffea46"],
}
# Paul Tol "bright", colour-blind safe. Class `none` stays transparent.
AI_COLOURS = {
    "none": (0, 0, 0, 0),
    "linear": (68, 119, 170, 210),
    "step": (238, 102, 119, 210),
    "accelerating": (204, 187, 68, 210),
    "seasonal_shift": (102, 204, 238, 210),
}
SIGNIFICANT_ALPHA = 215
FAINT_ALPHA = 90


def _hex(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _lut(palette: str) -> np.ndarray:
    anchors = np.array([_hex(item) for item in _ANCHORS[palette]], dtype=float)
    stops = np.linspace(0, 1, len(anchors))
    points = np.linspace(0, 1, 256)
    return np.stack([np.interp(points, stops, anchors[:, channel]) for channel in range(3)], axis=1).astype(np.uint8)


_LUTS = {name: _lut(name) for name in _ANCHORS}
_AI_TABLE = np.array([AI_COLOURS[name] for name in AI_CLASSES], dtype=np.uint8)


def pixel_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude of every pixel centre of a tile."""
    n = TILE_SIZE * 2**z
    offsets = np.arange(TILE_SIZE) + 0.5
    lon = (x * TILE_SIZE + offsets) / n * 360.0 - 180.0
    merc_y = np.pi * (1 - 2 * (y * TILE_SIZE + offsets) / n)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    return np.broadcast_to(lon[None, :], (TILE_SIZE, TILE_SIZE)), np.broadcast_to(lat[:, None], (TILE_SIZE, TILE_SIZE))


class PillowTileRenderer:
    def render(self, request: TileRequest, product: GridProduct, arrays: GridArrays) -> bytes:
        lon, lat = pixel_lonlat(request.z, request.x, request.y)
        west, _, _, north = product.bbox
        rows_total, cols_total = np.shape(arrays.values)
        rows = np.floor((north - lat) / product.resolution).astype(int)
        cols = np.floor((lon - west) / product.resolution).astype(int)
        inside = (rows >= 0) & (rows < rows_total) & (cols >= 0) & (cols < cols_total)
        rows = np.clip(rows, 0, rows_total - 1)
        cols = np.clip(cols, 0, cols_total - 1)

        significant = np.asarray(arrays.sig_fdr)[rows, cols].astype(bool)
        rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
        if request.product == "ai_class":
            classes = np.clip(np.asarray(arrays.ai_class)[rows, cols].astype(int), 0, len(AI_CLASSES) - 1)
            rgba[:] = _AI_TABLE[classes]
        else:
            values = np.asarray(arrays.values, dtype=float)[rows, cols]
            scaled = np.clip(np.nan_to_num((values / product.vmax + 1) / 2, nan=0.5), 0, 1)
            rgba[..., :3] = _LUTS[request.palette][(scaled * 255).astype(int)]
            # Opacity grows with the size of the trend, so a near-zero cell lets the basemap show through.
            strength = np.clip(np.nan_to_num(np.abs(values) / product.vmax, nan=0.0), 0, 1)
            base = np.where(significant, SIGNIFICANT_ALPHA, FAINT_ALPHA)
            rgba[..., 3] = np.rint(base * (0.2 + 0.8 * strength)).astype(np.uint8)
            rgba[..., 3] = np.where(np.isnan(values), 0, rgba[..., 3])
        if request.significant_only:
            rgba[..., 3] = np.where(significant, rgba[..., 3], 0)
        rgba[..., 3] = np.where(inside, rgba[..., 3], 0)
        return _png(rgba)

    def empty(self) -> bytes:
        return _png(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8))


def _png(rgba: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
