"""Case HTTP routes."""

from __future__ import annotations

from litestar import Request, Router, delete, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, JSONBody
from litestar.response import Response

from earthtrend.api.api.cases.schemas import (
    AnalyzeSeriesRequest,
    CaseResponse,
    CompareRequest,
    CompareResponse,
    CreateCaseRequest,
    EvidenceResponse,
    MonthResponse,
    ProfileLevelResponse,
    ProfileResponse,
    QualityResponse,
    UrbanResponse,
)
from earthtrend.api.api.shared.auth import require_actor
from pydantic import ValidationError

from earthtrend.analytics import AnalysisOptions, RegionalSeries, TrendResult
from earthtrend.api.application.cases.analyze_series import AnalyzeSeries, AnalyzeSeriesCommand
from earthtrend.api.domain.shared.errors import DomainError
from earthtrend.api.infrastructure.analytics_bridge import indicator_trend, run_blocking, series_from_grid
from earthtrend.api.infrastructure.shared.analytics_client import EmbeddedAnalyticsClient
from earthtrend.api.application.cases.service import CaseService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.cases.model import Case, CaseError, CaseSpec, UrbanContrast, VerticalProfile


def _http(error: CaseError) -> HTTPException:
    status = {
        "assignment_locked": 403,
        "forbidden": 403,
        "verdict_required": 422,
        "period_too_short": 422,
        "compare_invalid": 422,
    }.get(error.code, 404)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _response(case: Case) -> CaseResponse:
    verdict = None if case.verdict is None else {"code": case.verdict.code, "ruleset": case.verdict.ruleset}
    links = {}
    if case.status == "completed":
        links = {
            "evidence": f"/api/v1/cases/{case.id}/evidence",
            "profile": f"/api/v1/cases/{case.id}/profile",
            "urban": f"/api/v1/cases/{case.id}/urban",
            "story": f"/api/v1/cases/{case.id}/story",
            "export": f"/api/v1/cases/{case.id}/export",
        }
    return CaseResponse(
        id=case.id,
        status=case.status,
        variable_id=case.spec.variable_id,
        region_id=case.spec.region_id,
        period={"start": case.spec.period_start, "end": case.spec.period_end},
        job_id=case.job_id,
        verdict=verdict,
        evidence_version=None if case.evidence is None else case.evidence.version,
        datasets_version=case.datasets_version,
        slope_decade=None if case.series is None else case.series.slope_decade,
        direction=None if case.verdict is None else case.verdict.direction,
        links=links,
    )


def _profile(case_id: str, profile: VerticalProfile) -> ProfileResponse:
    return ProfileResponse(
        case_id=case_id,
        levels=[
            ProfileLevelResponse(
                pressure_hpa=level.pressure_hpa,
                slope=level.slope,
                low=level.low,
                high=level.high,
                p_value=level.p_value,
                pattern=level.pattern,
            )
            for level in profile.levels
        ],
    )


def _urban(case_id: str, urban: UrbanContrast) -> UrbanResponse:
    return UrbanResponse(
        case_id=case_id,
        city_slope=urban.city_slope,
        ring_slope=urban.ring_slope,
        difference=urban.difference,
    )


def cases_router(service: CaseService, identity: IdentityService) -> Router:
    @post("/analyze", status_code=200)
    async def analyze(data: JSONBody[AnalyzeSeriesRequest]) -> TrendResult:
        try:
            if data.indicator:
                return await run_blocking(indicator_trend, data.series, data.indicator, data.options)
            options = AnalysisOptions.model_validate(data.options or {})
            series = RegionalSeries.model_validate(data.series)
            return await AnalyzeSeries(EmbeddedAnalyticsClient())(
                AnalyzeSeriesCommand(series=series, options=options)
            )
        except (ValidationError, ValueError) as error:
            unknown = str(error).startswith("unknown indicator")
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "indicator_unknown" if unknown else "invalid_series",
                    "message": "Невідомий індикатор" if unknown else "Ряд не читається",
                    "details": {"errors": str(error)},
                },
            ) from error
        except DomainError as error:
            status = {"invalid_series": 422, "analytics_timeout": 504}.get(error.code, 500)
            raise HTTPException(
                status_code=status,
                detail={"code": error.code, "message": error.message, "details": error.details},
            ) from error

    @post("/cases")
    async def create_case(data: JSONBody[CreateCaseRequest], request: Request) -> Response[CaseResponse]:
        actor = await require_actor(request, identity)
        spec = CaseSpec(
            variable_id=data.variable_id,
            region_id=data.region_id,
            period_start=data.period_start,
            period_end=data.period_end,
            season=data.season,
            frequency=data.frequency,
            language=data.language,
            heavy=data.heavy,
        )
        try:
            payload = data.series
            if data.indicator and payload is None:
                raise ValueError("indicator needs a daily series")
            if data.grid is not None:
                payload = await run_blocking(series_from_grid, data.grid)
            case = await service.create(
                spec=spec,
                owner_id=actor.id,
                role=actor.role,
                series=payload,
                profile_levels=data.profile_levels,
                urban_cube=data.urban_cube,
                indicator=data.indicator,
            )
        except ValueError as error:
            unknown = str(error).startswith("unknown indicator")
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "indicator_unknown" if unknown else "invalid_series",
                    "message": "Невідомий індикатор" if unknown else "Ряд не читається",
                    "details": {"errors": str(error)},
                },
            ) from error
        except CaseError as error:
            raise _http(error) from error
        status = 202 if case.status == "queued" else 201
        return Response(content=_response(case), status_code=status)

    @get("/cases")
    async def list_cases(request: Request) -> list[CaseResponse]:
        actor = await require_actor(request, identity)
        cases = await service.list_cases(actor_id=actor.id, role=actor.role)
        return [_response(case) for case in cases]

    @get("/cases/{case_id:str}")
    async def get_case(case_id: FromPath[str], request: Request) -> CaseResponse:
        actor = await require_actor(request, identity)
        try:
            case = await service.get(case_id, actor_id=actor.id, role=actor.role)
        except CaseError as error:
            raise _http(error) from error
        return _response(case)

    @delete("/cases/{case_id:str}", status_code=204)
    async def delete_case(case_id: FromPath[str], request: Request) -> None:
        actor = await require_actor(request, identity)
        try:
            await service.delete(case_id, actor_id=actor.id, role=actor.role)
        except CaseError as error:
            raise _http(error) from error

    @post("/cases/compare")
    async def compare_cases(data: JSONBody[CompareRequest], request: Request) -> CompareResponse:
        actor = await require_actor(request, identity)
        try:
            created = await service.compare(
                variable_id=data.variable_id,
                region_ids=data.region_ids,
                period_start=data.period_start,
                period_end=data.period_end,
                season=data.season,
                frequency=data.frequency,
                language=data.language,
                owner_id=actor.id,
                role=actor.role,
            )
        except CaseError as error:
            raise _http(error) from error
        return CompareResponse(cases=[_response(case) for case in created])

    @get("/cases/{case_id:str}/evidence")
    async def get_evidence(case_id: FromPath[str], request: Request) -> EvidenceResponse:
        actor = await require_actor(request, identity)
        try:
            case = await service.get(case_id, actor_id=actor.id, role=actor.role)
            evidence = await service.evidence(case_id, actor_id=actor.id, role=actor.role)
        except CaseError as error:
            raise _http(error) from error
        if case.series is None:
            raise _http(CaseError("evidence_not_ready", "Протокол ще не збережено"))
        return EvidenceResponse(
            case_id=case_id,
            version=evidence.version,
            verdict_code=evidence.verdict_code,
            witnesses_confirmed=evidence.witnesses.confirmed,
            witnesses_total=evidence.witnesses.total,
            triangle_same_sign_share=evidence.triangle.same_sign_share,
            alibi_b_raw=evidence.alibi.b_raw,
            alibi_b_adjusted=evidence.alibi.b_adjusted,
            quality=QualityResponse(
                gap_fraction=evidence.quality.gap_fraction,
                stable_fraction=evidence.quality.stable_fraction,
                n_eff=evidence.quality.n_eff,
            ),
            months=[MonthResponse(month=item.month, slope=item.slope) for item in case.series.months],
            gam_accelerating=case.series.gam.accelerating,
        )

    @get("/cases/{case_id:str}/profile")
    async def get_profile(case_id: FromPath[str], request: Request) -> ProfileResponse:
        actor = await require_actor(request, identity)
        try:
            profile = await service.profile(case_id, actor_id=actor.id, role=actor.role)
        except CaseError as error:
            raise _http(error) from error
        return _profile(case_id, profile)

    @get("/cases/{case_id:str}/urban")
    async def get_urban(case_id: FromPath[str], request: Request) -> UrbanResponse:
        actor = await require_actor(request, identity)
        try:
            urban = await service.urban(case_id, actor_id=actor.id, role=actor.role)
        except CaseError as error:
            raise _http(error) from error
        return _urban(case_id, urban)

    return Router(
        path="/api/v1",
        route_handlers=[
            create_case,
            analyze,
            compare_cases,
            list_cases,
            get_case,
            delete_case,
            get_evidence,
            get_profile,
            get_urban,
        ],
    )
