"""Catalog HTTP schemas."""

from pydantic import BaseModel, ConfigDict, Field


class PassportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    name_uk: str
    kid_description: str
    units: str
    theme: str
    domain: str
    level: str
    witnesses: list[str]
    doi: str


class LinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    target_id: str
    direction: str


class SensorEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    kind: str
    year: int
    note: str


class PassportDetailResponse(PassportResponse):
    links: list[LinkResponse]
    events: list[SensorEventResponse]


class RegionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: str
    bbox: list[float]
    area_km2: float
    status: str
    geometry: dict | None = None
    ring: list[float] | None = None


class PotentialResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable_id: str
    season: str
    p_significant: float
    expected_sign: int
    reasons: list[str]


class CustomRegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    bbox: list[float] | None = None
    geometry: dict | None = None
    point: list[float] | None = None
    radius_km: float | None = None


class CmrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=200)


class CmrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    job_id: str | None = None


class ReloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(ge=1)
