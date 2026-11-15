"""Catalog HTTP routes."""

from __future__ import annotations

from litestar import Request, Response, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery, JSONBody

from earthtrend.api.api.catalog.schemas import (
    CmrRequest,
    CmrResponse,
    CustomRegionRequest,
    LinkResponse,
    PassportDetailResponse,
    PassportResponse,
    PotentialResponse,
    RegionResponse,
    ReloadResponse,
    SensorEventResponse,
)
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.catalog.model import CatalogError, Region, VariablePassport


def _http(error: CatalogError) -> HTTPException:
    status = {"variable_not_found": 404, "region_not_found": 404, "forbidden": 403}.get(error.code, 422)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _passport(item: VariablePassport) -> PassportResponse:
    return PassportResponse(
        id=item.id,
        name=item.name,
        name_uk=item.name_uk,
        kid_description=item.kid_description,
        units=item.units,
        theme=item.theme,
        domain=item.domain,
        level=item.level,
        witnesses=list(item.witnesses),
        doi=item.doi,
    )


def _detail(service: CatalogService, item: VariablePassport) -> PassportDetailResponse:
    base = _passport(item)
    return PassportDetailResponse(
        **base.model_dump(),
        links=[
            LinkResponse(source_id=link.source_id, target_id=link.target_id, direction=link.direction)
            for link in service.links_for(item.id)
        ],
        events=[
            SensorEventResponse(instrument=event.instrument, kind=event.kind, year=event.year, note=event.note)
            for event in service.events_for(item.id)
        ],
    )


def _region(item: Region) -> RegionResponse:
    return RegionResponse(
        id=item.id,
        name=item.name,
        kind=item.kind,
        bbox=list(item.bbox),
        area_km2=item.area_km2,
        status=item.status,
        geometry=item.geometry,
        ring=list(item.ring) if item.ring else None,
        name_uk=item.name_uk or item.name,
    )


def catalog_router(service: CatalogService, identity: IdentityService) -> Router:
    @get("/variables")
    async def list_variables(
        q: FromQuery[str | None] = None,
        theme: FromQuery[str | None] = None,
        domain: FromQuery[str | None] = None,
        level: FromQuery[str | None] = None,
    ) -> list[PassportResponse]:
        items = await service.list_variables(q, theme, domain, level)
        return [_passport(item) for item in items]

    @get("/variables/{variable_id:str}")
    async def get_variable(variable_id: FromPath[str]) -> PassportDetailResponse:
        try:
            return _detail(service, await service.get_variable(variable_id))
        except CatalogError as error:
            raise _http(error) from error

    @post("/variables/cmr")
    async def search_cmr(data: JSONBody[CmrRequest], request: Request) -> Response[CmrResponse]:
        await require_actor(request, identity)
        try:
            result = await service.search_cmr(data.query)
        except CatalogError as error:
            raise _http(error) from error
        body = CmrResponse(id=result.passport_id, job_id=result.job_id)
        return Response(content=body, status_code=200 if result.job_id is None else 202)

    @get("/regions")
    async def list_regions(q: FromQuery[str | None] = None) -> list[RegionResponse]:
        return [_region(item) for item in await service.list_regions(q)]

    @get("/regions/{region_id:str}")
    async def get_region(region_id: FromPath[str]) -> RegionResponse:
        try:
            return _region(await service.get_region(region_id))
        except CatalogError as error:
            raise _http(error) from error

    @get("/regions/{region_id:str}/potential")
    async def region_potential(region_id: FromPath[str]) -> list[PotentialResponse]:
        try:
            hints = await service.potential(region_id)
        except CatalogError as error:
            raise _http(error) from error
        return [
            PotentialResponse(
                variable_id=item.variable_id,
                season=item.season,
                p_significant=item.p_significant,
                expected_sign=item.expected_sign,
                reasons=list(item.reasons),
            )
            for item in hints
        ]

    @post("/regions/custom")
    async def register_custom(data: JSONBody[CustomRegionRequest], request: Request) -> RegionResponse:
        await require_actor(request, identity)
        bbox = tuple(data.bbox) if data.bbox is not None else None
        point = tuple(data.point) if data.point is not None else None
        try:
            region = await service.register_custom(
                name=data.name,
                bbox=bbox,
                geometry=data.geometry,
                point=point,  # type: ignore[arg-type]
                radius_km=data.radius_km,
            )
        except CatalogError as error:
            raise _http(error) from error
        return _region(region)

    @post("/admin/reload-catalog")
    async def reload_catalog(request: Request) -> ReloadResponse:
        actor = await require_actor(request, identity)
        try:
            generation = await service.reload(role=actor.role)
        except CatalogError as error:
            raise _http(error) from error
        return ReloadResponse(generation=generation)

    return Router(
        path="/api/v1",
        route_handlers=[
            list_variables,
            get_variable,
            search_cmr,
            list_regions,
            get_region,
            region_potential,
            register_custom,
            reload_catalog,
        ],
    )
