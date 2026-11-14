"""``GET /health``, ``/health/ready``, ``/health/live``."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from litestar import Response, get
from litestar.datastructures import State
from litestar.di import NamedDependency, Provide
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from earthtrend.api.application.health.check import HealthCheck


def provide_health_check(state: State) -> HealthCheck:
    return state.health_check


def _response(body: dict[str, Any], strict: bool) -> Response[dict[str, Any]]:
    degraded = body["status"] != "ok"
    status = HTTP_503_SERVICE_UNAVAILABLE if strict and degraded else HTTP_200_OK
    return Response(content=body, status_code=status)


@get("/health", summary="Overall status with dependency checks")
async def health(health_check: NamedDependency[HealthCheck]) -> Response[dict[str, Any]]:
    return _response(asdict(await health_check("full")), strict=False)


@get("/health/ready", summary="Readiness: 503 while the database or analytics is down")
async def health_ready(health_check: NamedDependency[HealthCheck]) -> Response[dict[str, Any]]:
    return _response(asdict(await health_check("ready")), strict=True)


@get("/health/live", summary="Liveness: the process answers")
async def health_live(health_check: NamedDependency[HealthCheck]) -> Response[dict[str, Any]]:
    return _response(asdict(await health_check("live")), strict=True)


health_handlers = [health, health_ready, health_live]
health_dependencies = {"health_check": Provide(provide_health_check, sync_to_thread=False)}
