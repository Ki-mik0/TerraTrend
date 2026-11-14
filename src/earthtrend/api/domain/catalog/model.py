"""Catalog aggregates. Demos and glossary are read from the catalog, not stored as their own lifecycle."""

from __future__ import annotations

import math
from dataclasses import dataclass

LEVELS = frozenset({"curated", "cmr"})
REGION_KINDS = frozenset(
    {"ar6", "country", "admin", "basin", "biome", "city", "ocean", "elevation", "demo", "preset", "custom"}
)


class CatalogError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ProcessLink:
    source_id: str
    target_id: str
    direction: str


@dataclass(frozen=True)
class SensorEvent:
    instrument: str
    kind: str
    year: int
    note: str


@dataclass(frozen=True)
class VariablePassport:
    id: str
    name: str
    name_uk: str
    kid_description: str
    units: str
    theme: str = ""
    domain: str = ""
    level: str = "curated"
    witnesses: tuple[str, ...] = ()
    doi: str = ""

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise CatalogError("level_invalid", "Невідомий рівень каталогу")

    def matches_text(self, query: str) -> bool:
        needle = query.casefold()
        haystack = " ".join((self.id, self.name, self.name_uk, self.kid_description)).casefold()
        return needle in haystack


@dataclass
class Region:
    id: str
    name: str
    kind: str
    bbox: tuple[float, float, float, float]
    area_km2: float
    status: str
    geometry: dict | None = None
    ring: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class TrendPotential:
    region_id: str
    variable_id: str
    season: str
    p_significant: float
    expected_sign: int
    reasons: tuple[str, ...]


@dataclass
class PotentialFeedback:
    region_id: str
    variable_id: str
    predicted_sign: int
    p_significant: float
    case_id: str
    actual_code: str


@dataclass(frozen=True)
class DemoStep:
    title: str
    text: str
    target: str = ""


@dataclass(frozen=True)
class DemoScenario:
    """A guided demo case. One record per language; the id is shared across languages."""

    id: str
    title: str
    language: str = "uk"
    summary: str = ""
    tool: str = ""
    variable_id: str = ""
    region_id: str = ""
    period_start: str = ""
    period_end: str = ""
    steps: tuple[DemoStep, ...] = ()


@dataclass(frozen=True)
class GlossaryEntry:
    """A glossary term, or a whole page (kind `page`) such as "How our AI works"."""

    id: str
    term: str
    text: str
    language: str = "uk"
    example: str = ""
    kind: str = "term"


def register_region(
    *,
    region_id: str,
    name: str,
    bbox: tuple[float, float, float, float] | None = None,
    geometry: dict | None = None,
    point: tuple[float, float] | None = None,
    radius_km: float | None = None,
) -> Region:
    choices = (bbox is not None, geometry is not None, point is not None)
    if sum(choices) != 1:
        raise CatalogError("region_invalid", "Потрібен один із: bbox, полігон або точка з радіусом")
    if bbox is not None and len(bbox) != 4:
        raise CatalogError("region_invalid", "bbox має чотири числа")
    if point is not None:
        if radius_km is None or radius_km <= 0 or len(point) != 2:
            raise CatalogError("region_invalid", "Точка потребує додатний радіус")
        box = _bbox_from_point(point, radius_km)
        geometry = {"type": "Point", "coordinates": [point[0], point[1]], "radius_km": radius_km}
        area = round(math.pi * radius_km * radius_km, 1)
    else:
        box = bbox if bbox is not None else _bbox_from_geometry(geometry)
        if box is None:
            raise CatalogError("region_invalid", "Полігон не читається")
        width = abs(box[2] - box[0])
        height = abs(box[3] - box[1])
        area = round(width * height * 1000, 1)
    return Region(
        id=region_id,
        name=name,
        kind="custom",
        bbox=box,
        area_km2=area,
        status="registered",
        geometry=geometry,
    )


def _bbox_from_point(point: tuple[float, float], radius_km: float) -> tuple[float, float, float, float]:
    lon, lat = point
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _bbox_from_geometry(geometry: dict | None) -> tuple[float, float, float, float] | None:
    if not geometry or geometry.get("type") != "Polygon":
        return None
    ring = geometry.get("coordinates", [[]])[0]
    if len(ring) < 3:
        return None
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return (min(lons), min(lats), max(lons), max(lats))
