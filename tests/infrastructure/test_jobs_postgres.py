"""Jobs against a real PostgreSQL. Skipped when the database is down."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.application.jobs.service import JobService
from earthtrend.api.domain.jobs.model import Job
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.jobs.postgres import PostgresJobStore

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DB_URL",
    "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend",
)
MOMENT = datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return MOMENT


class Lookup:
    async def get(self, case_id: str):
        return None


class CountingRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case_id: str) -> None:
        self.calls += 1


def _engine(url: str):
    return create_async_engine(url, poolclass=NullPool)


async def _reachable(url: str) -> None:
    engine = _engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if not DATABASE_URL.startswith("postgresql"):
        pytest.skip("DB_URL is not PostgreSQL")
    try:
        asyncio.run(_reachable(DATABASE_URL))
    except Exception as error:
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    return DATABASE_URL


@pytest.fixture
async def database(postgres_url: str):
    engine = _engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("TRUNCATE TABLE jobs"))
    store = PostgresJobStore(engine)
    yield store, engine
    await engine.dispose()


async def _scalar(engine, statement: str, **params):
    async with engine.connect() as connection:
        return await connection.scalar(text(statement), params)


async def test_two_workers_claim_one_job_and_keep_the_clock(database) -> None:
    store, engine = database
    runner = CountingRunner()
    service = JobService(cases=Lookup(), store=store, runner=runner, clock=FixedClock())
    queued = Job(id="job_case_race", case_id="case_race", created_at=MOMENT)
    assert await store.add(queued)
    await asyncio.gather(service.drive(queued.id), service.drive(queued.id))
    assert runner.calls == 2
    assert await _scalar(engine, "SELECT count(*) FROM jobs") == 1
    assert await _scalar(engine, "SELECT status FROM jobs WHERE id = :id", id=queued.id) == "completed"
    assert await _scalar(engine, "SELECT created_at FROM jobs WHERE id = :id", id=queued.id) == MOMENT
    names = await _scalar(
        engine,
        "SELECT string_agg(indexname, ',') FROM pg_indexes WHERE tablename = 'jobs'",
    )
    assert "jobs_status" in names
    assert "jobs_case" in names


async def test_invalid_status_rolls_back(database) -> None:
    _store, engine = database
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO jobs (id, case_id, status, progress, stage, message, attempts, events, created_at) "
                    "VALUES ('bad', 'case', 'nope', 0, 'queued', 'x', 0, '[]'::jsonb, :moment)"
                ),
                {"moment": MOMENT},
            )
    assert await _scalar(engine, "SELECT count(*) FROM jobs WHERE id = 'bad'") == 0


async def test_unreachable_database_writes_nothing(postgres_url: str) -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:1/earthtrend",
        poolclass=NullPool,
        connect_args={"timeout": 2},
    )
    store = PostgresJobStore(engine)
    with pytest.raises(Exception):
        await store.add(Job(id="job_down", case_id="case_down", created_at=MOMENT))
    await engine.dispose()
    del postgres_url


async def test_migration_roundtrip_restores_jobs(postgres_url: str) -> None:
    admin = _engine(postgres_url)
    async with admin.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_jobs_mig"))
        await autocommit.execute(text("CREATE DATABASE earthtrend_jobs_mig"))
    await admin.dispose()
    mig_url = postgres_url.rsplit("/", 1)[0] + "/earthtrend_jobs_mig"
    sync_url = mig_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")
    command.downgrade(config, "004_journal")
    probe = _engine(mig_url)
    async with probe.connect() as connection:
        gone = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'jobs'"
            )
        )
    assert gone == 0
    command.upgrade(config, "head")
    async with probe.connect() as connection:
        back = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'jobs'"
            )
        )
    assert back == 1
    await probe.dispose()
    async with _engine(postgres_url).connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_jobs_mig"))
