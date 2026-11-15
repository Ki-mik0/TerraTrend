"""Composition root: the only module that imports ``infrastructure`` (Plan_Backend rule 5).

Reads settings, builds port implementations, wires them into use cases and mounts the
zone routers under ``/api/v1``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from litestar import Litestar, Router
from litestar.config.cors import CORSConfig
from litestar.datastructures import State
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin, SwaggerRenderPlugin
from sqlalchemy.ext.asyncio import AsyncEngine

from earthtrend.api.api.cases.routes import cases_dependencies, cases_handlers
from earthtrend.api.api.health.routes import health_dependencies, health_handlers
from earthtrend.api.api.shared.errors import EXCEPTION_HANDLERS
from earthtrend.api.api.shared.logging import configure_logging, request_logging_middleware
from earthtrend.api.application.cases.analyze_series import AnalyzeSeries
from earthtrend.api.application.health.check import HealthCheck
from earthtrend.api.application.shared.analytics_port import AnalyticsPort
from earthtrend.api.infrastructure.shared.analytics_client import EmbeddedAnalyticsClient
from earthtrend.api.infrastructure.shared.session import SqlDatabaseProbe, create_engine
from earthtrend.api.settings import API_PREFIX, Settings, get_settings

MAX_BODY_BYTES = 2 * 1024 * 1024  # DATA_TO_BACKEND section 1


def app_version() -> str:
    try:
        return version("earthtrend")
    except PackageNotFoundError:
        return "0.0.0+local"


def create_app(
    settings: Settings | None = None, analytics: AnalyticsPort | None = None
) -> Litestar:
    """Build the app. Tests pass their own ``settings`` and, if needed, a fake ``analytics``."""
    settings = settings or get_settings()
    configure_logging(json_logs=settings.log_json)

    engine: AsyncEngine = create_engine(settings.db_url)
    analytics = analytics or EmbeddedAnalyticsClient(timeout_s=settings.analytics_timeout_s)
    state = State(
        {
            "settings": settings,
            "engine": engine,
            "analyze_series": AnalyzeSeries(analytics),
            "health_check": HealthCheck(app_version(), analytics, SqlDatabaseProbe(engine)),
        }
    )

    async def dispose_engine() -> None:
        await engine.dispose()

    api_v1 = Router(
        path=API_PREFIX,
        route_handlers=[*health_handlers, *cases_handlers],
        dependencies={**health_dependencies, **cases_dependencies},
    )

    return Litestar(
        route_handlers=[api_v1],
        state=state,
        exception_handlers=EXCEPTION_HANDLERS,
        middleware=[request_logging_middleware],
        cors_config=CORSConfig(allow_origins=settings.cors_origins, allow_credentials=True, expose_headers=["Content-Disposition"]),
        request_max_body_size=MAX_BODY_BYTES,
        on_shutdown=[dispose_engine],
        openapi_config=OpenAPIConfig(
            title="TerraTrend API",
            version=app_version(),
            path=f"{API_PREFIX}/schema",
            render_plugins=[ScalarRenderPlugin(), SwaggerRenderPlugin(path="/swagger")],
        ),
        debug=settings.debug,
    )
