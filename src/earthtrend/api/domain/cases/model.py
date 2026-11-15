"""Case aggregate. The domain stores a verdict; it does not calculate one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VERDICT_CODES = frozenset(
    {"proven", "strong", "likely", "suspicious", "no_evidence", "inadmissible"}
)
RULESET = "verdict_rules_v1"
MIN_PERIOD_MONTHS = 24


class CaseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def require_period(start: str, end: str) -> None:
    try:
        sy, sm = (int(part) for part in start.split("-"))
        ey, em = (int(part) for part in end.split("-"))
        if not (1 <= sm <= 12 and 1 <= em <= 12):
            raise ValueError
        months = (ey - sy) * 12 + (em - sm)
    except (ValueError, AttributeError):
        months = -1
    if months < MIN_PERIOD_MONTHS:
        raise CaseError("period_too_short", "Період коротший за 24 місяці")


def require_compare_count(count: int) -> None:
    if count < 2 or count > 4:
        raise CaseError("compare_invalid", "Потрібно від двох до чотирьох регіонів")


@dataclass(frozen=True)
class CaseSpec:
    variable_id: str
    region_id: str
    period_start: str
    period_end: str
    season: str | None = None
    frequency: str = "monthly"
    language: str = "uk"
    heavy: bool = False


@dataclass(frozen=True)
class Verdict:
    code: str
    ruleset: str
    direction: str
    summary: str

    def __post_init__(self) -> None:
        if self.code not in VERDICT_CODES or self.ruleset != RULESET:
            raise CaseError("verdict_required", "Завершена справа потребує коду verdict_rules_v1")


@dataclass(frozen=True)
class WitnessesResult:
    confirmed: int
    total: int


@dataclass(frozen=True)
class TriangleResult:
    same_sign_share: float


@dataclass(frozen=True)
class AlibiResult:
    b_raw: float
    b_adjusted: float


@dataclass(frozen=True)
class QualityResult:
    gap_fraction: float
    stable_fraction: float
    n_eff: float


@dataclass(frozen=True)
class JackknifeResult:
    influential_year: int | None


@dataclass(frozen=True)
class Changepoint:
    year: int
    probability: float


@dataclass(frozen=True)
class SplitResult:
    split_flag: bool
    sig_pos: float
    sig_neg: float


@dataclass(frozen=True)
class Zone:
    sign: int
    slope_decade: float


@dataclass(frozen=True)
class MonthSlope:
    month: int
    slope: float


@dataclass(frozen=True)
class GamResult:
    accelerating: bool


@dataclass(frozen=True)
class SeriesArtifact:
    slope_decade: float
    split: SplitResult
    jackknife: JackknifeResult
    changepoints: tuple[Changepoint, ...] = ()
    zones: tuple[Zone, ...] = ()
    months: tuple[MonthSlope, ...] = ()
    gam: GamResult = field(default_factory=lambda: GamResult(False))


@dataclass(frozen=True)
class AiOpinion:
    predicted_class: str
    confidence: str
    advisory: bool = True
    disagrees: bool = False


@dataclass(frozen=True)
class EvidenceProtocol:
    version: str
    witnesses: WitnessesResult
    triangle: TriangleResult
    alibi: AlibiResult
    verdict_code: str
    quality: QualityResult


@dataclass(frozen=True)
class VerticalLevel:
    pressure_hpa: int
    slope: float
    low: float
    high: float
    p_value: float
    pattern: str


@dataclass(frozen=True)
class VerticalProfile:
    levels: tuple[VerticalLevel, ...]


@dataclass(frozen=True)
class UrbanContrast:
    city_slope: float
    ring_slope: float
    difference: float


@dataclass(frozen=True)
class AnalysisProduct:
    verdict: Verdict
    evidence: EvidenceProtocol
    series: SeriesArtifact
    profile: VerticalProfile
    urban: UrbanContrast
    catalog_version: str
    datasets_version: str
    algorithm_version: str
    result_hash: str
    # The TrendNet opinion when the analytics computed one; never part of the result hash.
    ai_opinion: AiOpinion | None = None


@dataclass
class Case:
    id: str
    owner_id: str
    role: str
    spec: CaseSpec
    status: str = "queued"
    ephemeral: bool = False
    assignment_linked: bool = False
    job_id: str | None = None
    source_series: dict | None = None
    verdict: Verdict | None = None
    evidence: EvidenceProtocol | None = None
    series: SeriesArtifact | None = None
    ai_opinion: AiOpinion | None = None
    profile: VerticalProfile | None = None
    urban: UrbanContrast | None = None
    catalog_version: str = ""
    datasets_version: str = ""
    algorithm_version: str = ""
    result_hash: str = ""
    warnings: list[str] = field(default_factory=list)

    def visible_to(self, actor_id: str, role: str) -> bool:
        if role == "admin":
            return True
        return self.owner_id == actor_id

    def listed_for(self, actor_id: str, role: str) -> bool:
        if role == "guest" or self.ephemeral:
            return False
        return self.owner_id == actor_id

    def complete(
        self,
        *,
        verdict: Verdict,
        evidence: EvidenceProtocol,
        series: SeriesArtifact,
        ai_opinion: AiOpinion | None,
        profile: VerticalProfile,
        urban: UrbanContrast,
        catalog_version: str,
        datasets_version: str,
        algorithm_version: str,
        result_hash: str,
    ) -> None:
        if evidence.verdict_code != verdict.code or evidence.version == "":
            raise CaseError("verdict_required", "Протокол не збігається з вироком")
        if len(series.months) != 12:
            raise CaseError("verdict_required", "Ряд потребує дванадцяти місяців")
        self.verdict = verdict
        self.evidence = evidence
        self.series = series
        self.ai_opinion = ai_opinion
        self.profile = profile
        self.urban = urban
        self.catalog_version = catalog_version
        self.datasets_version = datasets_version
        self.algorithm_version = algorithm_version
        self.result_hash = result_hash
        self.status = "completed"
        self.job_id = None

    def queue(self, job_id: str) -> None:
        self.status = "queued"
        self.job_id = job_id

    def assert_deletable(self, actor_id: str, role: str) -> None:
        if self.assignment_linked and role != "admin":
            raise CaseError("assignment_locked", "Справу завдання видаляє лише admin")
        if role == "admin" or self.owner_id == actor_id:
            return
        raise CaseError("forbidden", "Видалити справу може власник або admin")


def assert_storable(case: Case) -> None:
    if case.status == "completed" and (
        case.verdict is None or case.verdict.code not in VERDICT_CODES or case.evidence is None
    ):
        raise CaseError("verdict_required", "Завершену справу без вироку не зберігаємо")


def snapshot(case: Case) -> dict[str, Any]:
    verdict = None if case.verdict is None else {"code": case.verdict.code, "ruleset": case.verdict.ruleset}
    return {
        "id": case.id,
        "status": case.status,
        "owner_id": case.owner_id,
        "ephemeral": case.ephemeral,
        "job_id": case.job_id,
        "variable_id": case.spec.variable_id,
        "region_id": case.spec.region_id,
        "period": {"start": case.spec.period_start, "end": case.spec.period_end},
        "verdict": verdict,
        "evidence_version": None if case.evidence is None else case.evidence.version,
    }
