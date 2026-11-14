"""Export HTTP routes."""

from __future__ import annotations

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, JSONBody
from litestar.response import Response

from earthtrend.api.api.exports.schemas import ExportRequest, ExportResponse
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.exports.service import ExportService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.exports.model import ExportError, ExportRecord
from earthtrend.api.infrastructure.exports.render import MEDIA


def _http(error: ExportError) -> HTTPException:
    status = 422 if error.code == "format_invalid" else 404
    if error.code == "case_not_ready":
        status = 409
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _body(record: ExportRecord) -> ExportResponse:
    url = None
    if record.status == "ready":
        url = f"/api/v1/exports/{record.id}/download"
    return ExportResponse(
        id=record.id,
        case_id=record.case_id,
        format=record.format,
        status=record.status,
        download_url=url,
    )


def exports_router(service: ExportService, identity: IdentityService) -> Router:
    @post("/cases/{case_id:str}/export", status_code=202)
    async def create_export(
        case_id: FromPath[str], data: JSONBody[ExportRequest], request: Request
    ) -> ExportResponse:
        actor = await require_actor(request, identity)
        try:
            record = await service.create(case_id=case_id, fmt=data.format, actor_id=actor.id)
        except ExportError as error:
            raise _http(error) from error
        return _body(record)

    @get("/exports/{export_id:str}")
    async def get_export(export_id: FromPath[str], request: Request) -> ExportResponse:
        actor = await require_actor(request, identity)
        try:
            record = await service.get(export_id, actor_id=actor.id)
        except ExportError as error:
            raise _http(error) from error
        return _body(record)

    @get("/exports/{export_id:str}/download")
    async def download_export(export_id: FromPath[str], request: Request) -> Response:
        actor = await require_actor(request, identity)
        try:
            record = await service.get(export_id, actor_id=actor.id)
            body = await service.download(export_id, actor_id=actor.id)
        except ExportError as error:
            raise _http(error) from error
        return Response(content=body, media_type=MEDIA[record.format])

    return Router(path="/api/v1", route_handlers=[create_export, get_export, download_export])
