"""Tile HTTP schemas."""

from pydantic import BaseModel


class GridProductResponse(BaseModel):
    variable_id: str
    period: str
    season: str
    data_version: str
    bbox: list[float]
    resolution: float
    vmax: float
    years: list[int]
    products: list[str]
    palettes: list[str]
    tile_url: str
