"""Wire the case slice with memory, or with PostgreSQL when DB_URL points there."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.cases.ports import CaseStore
from earthtrend.api.application.cases.service import CaseService
from earthtrend.api.infrastructure.cases.memory import (
    MemoryAnalysis,
    MemoryAssignments,
    MemoryCaseStore,
    MemoryJobs,
)
from earthtrend.api.infrastructure.cases.postgres import PostgresCaseStore
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.shared.cache import MemoryCache


def build_case_service(
    *,
    store: CaseStore | None = None,
    assignments: MemoryAssignments | None = None,
    jobs: MemoryJobs | None = None,
    feedback=None,
    remember=None,
    achievements=None,
    catalog=None,
    cache=None,
    analysis: MemoryAnalysis | None = None,
) -> CaseService:
    return CaseService(
        store=store or MemoryCaseStore(),
        analysis=analysis or MemoryAnalysis(),
        jobs=jobs or MemoryJobs(),
        assignments=assignments or MemoryAssignments(),
        feedback=feedback,
        remember=remember,
        achievements=achievements,
        catalog=seed_catalog() if catalog is None else catalog,
        cache=MemoryCache() if cache is None else cache,
    )


def case_store_from_env() -> tuple[CaseStore, object | None]:
    url = os.environ.get("DB_URL", "")
    if url.startswith("postgresql"):
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        store = PostgresCaseStore(engine)

        async def prepare() -> None:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        return store, prepare
    return MemoryCaseStore(), None
