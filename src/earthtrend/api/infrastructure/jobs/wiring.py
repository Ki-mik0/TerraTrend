"""Wire jobs to memory, or to PostgreSQL when DB_URL points there."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.jobs.service import CaseLookup, JobService
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.jobs.postgres import PostgresJobStore


def build_job_service(cases: CaseLookup) -> JobService:
    return JobService(cases=cases)


def build_postgres_jobs(url: str, cases: CaseLookup) -> tuple[JobService, object]:
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    service = JobService(cases=cases, store=PostgresJobStore(engine))

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    return service, prepare


def jobs_from_env(cases: CaseLookup) -> tuple[JobService, object | None]:
    url = os.environ.get("DB_URL", "")
    if url.startswith("postgresql"):
        return build_postgres_jobs(url, cases)
    return build_job_service(cases), None
