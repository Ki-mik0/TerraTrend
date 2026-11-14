"""Radar HTTP schemas."""

from typing import Literal

from pydantic import BaseModel


class RadarCardResponse(BaseModel):
    id: str
    feed: str
    variable_id: str
    region_id: str
    season: str
    direction: str
    slope_decade: float
    pct_decade: float
    snr: float
    p_mk: float
    p_ols: float
    q_fdr: float
    split_flag: bool
    score: float
    verdict_level: str
    novelty: Literal["new", "upgraded", "downgraded", "unchanged"]
    years_to_detect: float | None = None
    area_km2: float
    case_id: str
    case_url: str


class RadarPageResponse(BaseModel):
    """One page of a feed. `label` reminds the reader these are candidates after the FDR correction."""

    items: list[RadarCardResponse]
    page: int
    page_size: int
    total: int
    data_version: str
    generated_at: str
    label: str


class TypologyClusterResponse(BaseModel):
    id: str
    pattern: str
    signs: dict[str, int]
    season: str
    area_km2: float
    region_ids: list[str]
    geometry: dict | None = None


class TypologyResponse(BaseModel):
    data_version: str
    clusters: list[TypologyClusterResponse]


class RadarScanRequest(BaseModel):
    series: list[dict]
