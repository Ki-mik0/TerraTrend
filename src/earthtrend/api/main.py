"""Litestar app: every zone wired here, the only module that imports infrastructure."""

import os

from litestar import Litestar
from litestar.plugins.prometheus import PrometheusConfig, PrometheusController
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import JsonRenderPlugin, ScalarRenderPlugin

from earthtrend.api.api.assistant.routes import assistant_router
from earthtrend.api.api.cache.routes import cache_router
from earthtrend.api.api.cases.routes import cases_router
from earthtrend.api.api.catalog.routes import catalog_router
from earthtrend.api.api.education.routes import education_router
from earthtrend.api.api.exports.routes import exports_router
from earthtrend.api.api.health.routes import health_router
from earthtrend.api.api.identity.routes import identity_router
from earthtrend.api.api.jobs.routes import jobs_router
from earthtrend.api.api.journal.routes import journal_router
from earthtrend.api.api.radar.routes import radar_router
from earthtrend.api.api.story.routes import story_router
from earthtrend.api.api.tiles.routes import tiles_router
from earthtrend.api.application.cache.service import CacheAdmin
from earthtrend.api.application.assistant.service import AssistantService
from earthtrend.api.application.cases.service import CaseService
from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.application.education.service import EducationService
from earthtrend.api.application.exports.service import ExportService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.application.jobs.service import JobService
from earthtrend.api.application.journal.service import JournalService
from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.application.story.service import StoryService
from earthtrend.api.infrastructure.assistant.live import (
    LiveCases,
    LiveCatalog,
    LiveEvidence,
    LiveNotes,
    LiveProfile,
    LiveRadar,
    LiveStory,
    LiveUrban,
)
from earthtrend.api.infrastructure.assistant.wiring import Neighbors, assistant_from_env
from earthtrend.api.infrastructure.cases.memory import MemoryAssignments
from earthtrend.api.infrastructure.cases.sources import sourced_analysis_from_env
from earthtrend.api.infrastructure.cases.wiring import build_case_service, case_store_from_env
from earthtrend.api.infrastructure.catalog.wiring import catalog_from_env
from earthtrend.api.infrastructure.education.wiring import education_from_env
from earthtrend.api.infrastructure.health.wiring import health_from_env
from earthtrend.api.infrastructure.identity.wiring import identity_from_env
from earthtrend.api.infrastructure.shared.snapshot import persist
from earthtrend.api.infrastructure.jobs.wiring import jobs_from_env
from earthtrend.api.infrastructure.journal.wiring import journal_from_env
from earthtrend.api.infrastructure.radar.wiring import radar_from_env
from earthtrend.api.infrastructure.shared.cache import cache_from_env
from earthtrend.api.infrastructure.shared.storage import LocalObjectStorage
from earthtrend.api.infrastructure.shared.warmers import (
    education_warmer,
    prometheus_stats,
    radar_warmer,
    tiles_warmer,
)
from earthtrend.api.infrastructure.story.wiring import story_from_env
from earthtrend.api.infrastructure.tiles.wiring import storage_root, tiles_from_env


class MetricsController(PrometheusController):
    path = "/metrics"
    include_in_schema = False


def metrics_config() -> PrometheusConfig:
    """`http_requests_total` and `http_request_duration_seconds`; health and metrics are not counted."""
    return PrometheusConfig(app_name="earthtrend", prefix="http", exclude=["/metrics", "/health"], group_path=True)


def create_app(
    service: AssistantService | None = None,
    cases: CaseService | None = None,
    catalog: CatalogService | None = None,
    education: EducationService | None = None,
    exports: ExportService | None = None,
    identity: IdentityService | None = None,
    jobs: JobService | None = None,
    journal: JournalService | None = None,
    radar: RadarService | None = None,
    story: StoryService | None = None,
) -> Litestar:
    shared_cache = cache_from_env()
    storage = LocalObjectStorage(storage_root())
    prepare_catalog = None
    if catalog is not None:
        catalog_service = catalog
    else:
        catalog_service, prepare_catalog = catalog_from_env(cache=shared_cache)
    links = MemoryAssignments() if cases is not None else persist(MemoryAssignments(), "assignment_links", ("linked",))
    startup: list = []
    prepare_cases = None
    if cases is None:
        case_lookup, prepare_cases = case_store_from_env()
    else:
        case_lookup = cases._store
    if education is not None:
        education_service = education
    else:
        education_service, prepare_education = education_from_env(
            lessons=catalog_service,
            cases=case_lookup,
            links=None if cases is not None else links,
            cache=shared_cache,
        )
        if prepare_education is not None:
            startup.append(prepare_education)
    if jobs is not None:
        job_service = jobs
        prepare_jobs = None
    else:
        job_service, prepare_jobs = jobs_from_env(case_lookup)
    if journal is not None:
        journal_service = journal
        prepare_journal = None
    else:
        journal_service, prepare_journal = journal_from_env(case_lookup)
    if cases is None:
        case_service = build_case_service(
            store=case_lookup,
            assignments=links,
            feedback=catalog_service,
            catalog=catalog_service,
            jobs=job_service,
            remember=journal_service,
            achievements=education_service,
            cache=shared_cache,
            analysis=sourced_analysis_from_env(catalog_service, shared_cache),
        )
    else:
        case_service = cases
    if jobs is None:
        job_service.attach_finisher(case_service.finish_queued)
    export_service = exports if exports is not None else ExportService(cases=case_lookup, catalog=catalog_service)
    if identity is not None:
        identity_service = identity
    else:
        identity_service, prepare = identity_from_env()
        if prepare is not None:
            startup.append(prepare)
    if prepare_catalog is not None:
        startup.append(prepare_catalog)
    if prepare_cases is not None:
        startup.append(prepare_cases)
    if prepare_jobs is not None:
        startup.append(prepare_jobs)
    if prepare_journal is not None:
        startup.append(prepare_journal)
    radar_service = radar if radar is not None else radar_from_env(cache=shared_cache)
    story_service = (
        story if story is not None else story_from_env(cases=case_lookup, catalog=catalog_service, cache=shared_cache)
    )
    tile_service = tiles_from_env(catalog_service, storage)
    cache_admin = CacheAdmin(
        cache=shared_cache,
        storage=storage,
        audit=identity_service,
        warmers={
            "radar": radar_warmer(radar_service),
            "education": education_warmer(education_service),
            "tiles": tiles_warmer(tile_service),
        },
        stats=prometheus_stats,
        backend="redis" if os.environ.get("REDIS_URL") else "memory",
    )
    health = health_from_env(
        cache_ping=shared_cache.ping,
        storage_ping=storage.ping,
        product_versions={"radar": radar_service.version, "grids": tile_service.grid_version},
    )
    metrics = metrics_config()
    if service is not None:
        assistant = service
    else:
        assistant, prepare_assistant = assistant_from_env(
            Neighbors(
                catalog=LiveCatalog(catalog_service),
                cases=LiveCases(case_service),
                evidence=LiveEvidence(case_service),
                story=LiveStory(story_service),
                profile=LiveProfile(case_service),
                urban=LiveUrban(case_service),
                radar=LiveRadar(radar_service),
                notes=LiveNotes(journal_service),
            )
        )
        if prepare_assistant is not None:
            startup.append(prepare_assistant)
    return Litestar(
        route_handlers=[
            assistant_router(assistant, identity_service),
            cases_router(case_service, identity_service),
            catalog_router(catalog_service, identity_service),
            education_router(education_service, identity_service),
            exports_router(export_service, identity_service),
            identity_router(identity_service),
            jobs_router(job_service, identity_service),
            journal_router(journal_service, identity_service),
            radar_router(radar_service),
            story_router(story_service, identity_service),
            tiles_router(tile_service),
            cache_router(cache_admin, identity_service),
            health_router(health),
            MetricsController,
        ],
        middleware=[metrics.middleware],
        openapi_config=OpenAPIConfig(
            title="EarthTrend API",
            version="1.0.0",
            render_plugins=[ScalarRenderPlugin(path=["/", "/scalar"]), JsonRenderPlugin()],
        ),
        on_startup=startup,
    )
