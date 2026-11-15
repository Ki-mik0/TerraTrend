"""Map tiles. A tile is a reading of a precomputed `GridTrendProduct`, never a new calculation."""

from __future__ import annotations

import re
from dataclasses import dataclass

PRODUCTS = frozenset({"trend", "ai_class"})
PALETTES = frozenset({"rdbu", "puor", "cividis"})
SEASONS = frozenset({"annual", "DJF", "MAM", "JJA", "SON"})
AI_CLASSES = ("none", "linear", "step", "accelerating", "seasonal_shift")
MAX_ZOOM = 12
TILE_SIZE = 256
_PERIOD = re.compile(r"^(\d{4})-(\d{4})$")


class TileError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def parse_period(period: str) -> tuple[int, int]:
    match = _PERIOD.match(period)
    if match is None:
        raise TileError("period_invalid", "Період має вигляд РРРР-РРРР")
    start, end = int(match.group(1)), int(match.group(2))
    if start >= end:
        raise TileError("period_invalid", "Початок періоду має бути раніше за кінець")
    return start, end


@dataclass(frozen=True)
class TileRequest:
    product: str
    z: int
    x: int
    y: int
    variable_id: str
    period: str
    season: str = "annual"
    palette: str = "rdbu"
    significant_only: bool = False
    year: int | None = None

    def __post_init__(self) -> None:
        if self.product not in PRODUCTS:
            raise TileError("product_invalid", "Продукт тайла — trend або ai_class")
        if not 0 <= self.z <= MAX_ZOOM:
            raise TileError("tile_out_of_range", f"Масштаб від 0 до {MAX_ZOOM}")
        limit = 2**self.z
        if not (0 <= self.x < limit and 0 <= self.y < limit):
            raise TileError("tile_out_of_range", "Координати тайла поза сіткою цього масштабу")
        if self.palette not in PALETTES:
            raise TileError("palette_invalid", "Палітра має бути rdbu, puor або cividis")
        if self.season not in SEASONS:
            raise TileError("season_invalid", "Сезон має бути annual, DJF, MAM, JJA або SON")
        start, end = parse_period(self.period)
        if self.year is not None and not start <= self.year <= end:
            raise TileError("year_invalid", "Рік кадру має лежати в періоді")

    def bounds(self) -> tuple[float, float, float, float]:
        """West, south, east, north of the tile in degrees (Web Mercator)."""
        return (*tile_lonlat(self.x, self.y + 1, self.z), *tile_lonlat(self.x + 1, self.y, self.z))

    def storage_key(self, version: str) -> str:
        frame = "all" if self.year is None else str(self.year)
        flag = "sig" if self.significant_only else "all"
        return (
            f"tile/{version}/{self.product}/{self.variable_id}/{self.period}/{self.season}/"
            f"{self.palette}/{flag}/{frame}/{self.z}/{self.x}/{self.y}.png"
        )


def tile_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    import math

    n = 2.0**z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


@dataclass(frozen=True)
class GridProduct:
    """Metadata of one `GridTrendProduct`. The arrays stay in the grid store."""

    variable_id: str
    period: str
    season: str
    version: str
    bbox: tuple[float, float, float, float]
    resolution: float
    vmax: float
    years: tuple[int, ...] = ()
    file: str = ""
    # Colour scale of the yearly anomaly frames (variable units); `vmax` is per decade.
    frame_vmax: float | None = None

    def __post_init__(self) -> None:
        parse_period(self.period)
        west, south, east, north = self.bbox
        if not (west < east and south < north) or not self.resolution > 0 or not 0 < self.vmax < float("inf"):
            raise TileError("grid_invalid", "Некоректні межі, роздільність або vmax сітки")
        if self.frame_vmax is not None and not 0 < self.frame_vmax < float("inf"):
            raise TileError("grid_invalid", "Некоректний frame_vmax сітки")

    def overlaps(self, bounds: tuple[float, float, float, float]) -> bool:
        west, south, east, north = bounds
        g_west, g_south, g_east, g_north = self.bbox
        return west < g_east and east > g_west and south < g_north and north > g_south

    def scale(self, year: int | None) -> float:
        """Colour scale: per-decade trend, or the anomaly of one year's frame."""
        return self.frame_vmax if year is not None and self.frame_vmax else self.vmax

    def has_frame(self, year: int | None) -> bool:
        return year is None or year in self.years
