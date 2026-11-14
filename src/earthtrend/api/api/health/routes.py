"""Health routes, outside `/api/v1` so load balancers and Docker use stable paths."""

from __future__ import annotations

from litestar import Router, get
from litestar.response import Response
from pydantic import BaseModel

from earthtrend.api.application.health.service import HealthCheck, HealthReport


class ProbeResponse(BaseModel):
    status: str
    detail: str
    latency_ms: float
    info: dict[str, str]


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    checks: dict[str, ProbeResponse]


def _body(report: HealthReport) -> HealthResponse:
    return HealthResponse(
        status=report.status,
        version=report.version,
        uptime_seconds=report.uptime_seconds,
        checks={
            name: ProbeResponse(status=item.status, detail=item.detail, latency_ms=item.latency_ms, info=item.info)
            for name, item in report.checks.items()
        },
    )


def _respond(report: HealthReport) -> Response[HealthResponse]:
    return Response(
        content=_body(report),
        status_code=200 if report.serving else 503,
        headers={"Cache-Control": "no-store"},
    )


def health_router(health: HealthCheck) -> Router:
    @get("/live", summary="Liveness: the process answers")
    async def live() -> Response[HealthResponse]:
        return _respond(health.live())

    @get("/ready", summary="Readiness: critical dependencies answer")
    async def ready() -> Response[HealthResponse]:
        return _respond(await health.ready())

    @get("/", summary="Full health report")
    async def full() -> Response[HealthResponse]:
        return _respond(await health.full())

    return Router(path="/health", route_handlers=[live, ready, full])
