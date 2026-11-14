"""Radar HTTP routes. Public: a guest may read the radar."""

from __future__ import annotations

import hashlib
from typing import Literal

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromQuery, JSONBody
from litestar.response import Response

from earthtrend.api.api.radar.schemas import (
    RadarCardResponse,
    RadarPageResponse,
    RadarScanRequest,
    TypologyClusterResponse,
    TypologyResponse,
)
from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.domain.radar.model import RadarError, RadarItem

CACHE_CONTROL = "public, max-age=300"
LABELS = {
    "uk": "Статистичні кандидати після поправки FDR на множинні порівняння, не доведені відкриття.",
    "en": "Statistical candidates after the FDR correction for multiple comparisons, not proven discoveries.",
}


def _card(item: RadarItem) -> RadarCardResponse:
    return RadarCardResponse(
        id=item.id,
        feed=item.feed,
        variable_id=item.variable_id,
        region_id=item.region_id,
        season=item.season,
        direction=item.direction,
        slope_decade=item.slope_decade,
        pct_decade=item.pct_decade,
        snr=item.snr,
        p_mk=item.p_mk,
        p_ols=item.p_ols,
        q_fdr=item.q_fdr,
        split_flag=item.split_flag,
        score=item.score,
        verdict_level=item.verdict_level,
        novelty=item.novelty,  # type: ignore[arg-type]
        years_to_detect=item.years_to_detect,
        area_km2=item.area_km2,
        case_id=item.case_id,
        case_url=item.case_url,
    )


def _etag(version: str, request: Request) -> str:
    digest = hashlib.sha256(f"{version}?{request.url.query}".encode()).hexdigest()[:20]
    return f'"{digest}"'


def _not_modified(request: Request, etag: str) -> bool:
    sent = request.headers.get("if-none-match", "")
    return etag in {tag.strip() for tag in sent.split(",")} or sent.strip() == "*"


def _http(error: RadarError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "message": error.message})


def radar_router(service: RadarService) -> Router:
    @get("/radar")
    async def get_radar(
        request: Request,
        feed: FromQuery[str] = "strongest",
        variable_id: FromQuery[str | None] = None,
        region_id: FromQuery[str | None] = None,
        season: FromQuery[str | None] = None,
        page: FromQuery[int] = 1,
        page_size: FromQuery[int] = 20,
        lang: FromQuery[Literal["uk", "en"]] = "uk",
    ) -> Response[RadarPageResponse]:
        try:
            result = await service.page(
                feed=feed,
                variable_id=variable_id,
                region_id=region_id,
                season=season,
                page=page,
                page_size=page_size,
            )
        except RadarError as error:
            raise _http(error) from error
        etag = _etag(result.version, request)
        headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
        if _not_modified(request, etag):
            return Response(content=None, status_code=304, headers=headers)
        body = RadarPageResponse(
            items=[_card(item) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            data_version=result.version,
            generated_at=result.generated_at,
            label=LABELS[lang],
        )
        return Response(content=body, headers=headers)

    @get("/radar/typology")
    async def get_typology(
        request: Request,
        variables: FromQuery[str | None] = None,
        season: FromQuery[str | None] = None,
    ) -> Response[TypologyResponse]:
        wanted = [item.strip() for item in (variables or "").split(",") if item.strip()]
        try:
            version, clusters = await service.typology(variables=wanted or None, season=season)
        except RadarError as error:
            raise _http(error) from error
        etag = _etag(version, request)
        headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
        if _not_modified(request, etag):
            return Response(content=None, status_code=304, headers=headers)
        body = TypologyResponse(
            data_version=version,
            clusters=[
                TypologyClusterResponse(
                    id=item.id,
                    pattern=item.pattern,
                    signs=dict(item.signs),
                    season=item.season,
                    area_km2=item.area_km2,
                    region_ids=list(item.region_ids),
                    geometry=item.geometry,
                )
                for item in clusters
            ],
        )
        return Response(content=body, headers=headers)

    @post("/radar/scan", status_code=200)
    async def scan_radar(data: JSONBody[RadarScanRequest]) -> dict:
        return await service.scan(data.series)

    return Router(path="/api/v1", route_handlers=[get_radar, get_typology, scan_radar])
