"""Case HTTP schemas."""

from pydantic import BaseModel, ConfigDict, Field


class CreateCaseRequest(BaseModel):
    variable_id: str
    region_id: str
    period_start: str
    period_end: str
    season: str | None = None
    frequency: str = "monthly"
    language: str = "uk"
    heavy: bool = False
    series: dict | None = None
    grid: dict | None = None
    profile_levels: dict | None = None
    urban_cube: dict | None = None


class AnalyzeSeriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series: dict
    options: dict | None = None


class CompareRequest(BaseModel):
    variable_id: str
    region_ids: list[str]
    period_start: str
    period_end: str
    season: str | None = None
    frequency: str = "monthly"
    language: str = "uk"


class CaseResponse(BaseModel):
    id: str
    status: str
    variable_id: str
    region_id: str
    period: dict[str, str]
    job_id: str | None = None
    verdict: dict[str, str] | None = None
    evidence_version: str | None = None
    links: dict[str, str] = Field(default_factory=dict)


class CompareResponse(BaseModel):
    cases: list[CaseResponse]


class QualityResponse(BaseModel):
    gap_fraction: float
    stable_fraction: float
    n_eff: float


class MonthResponse(BaseModel):
    month: int
    slope: float


class EvidenceResponse(BaseModel):
    case_id: str
    version: str
    verdict_code: str
    witnesses_confirmed: int
    witnesses_total: int
    triangle_same_sign_share: float
    alibi_b_raw: float
    alibi_b_adjusted: float
    quality: QualityResponse
    months: list[MonthResponse]
    gam_accelerating: bool


class ProfileLevelResponse(BaseModel):
    pressure_hpa: int
    slope: float
    low: float
    high: float
    p_value: float
    pattern: str


class ProfileResponse(BaseModel):
    case_id: str
    levels: list[ProfileLevelResponse]


class UrbanResponse(BaseModel):
    case_id: str
    city_slope: float
    ring_slope: float
    difference: float
