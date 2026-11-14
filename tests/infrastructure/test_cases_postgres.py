"""Cases against a real PostgreSQL. Skipped when the database is down."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.application.cases.service import CaseService
from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis, MemoryAssignments, MemoryJobs
from earthtrend.api.infrastructure.cases.postgres import PostgresCaseStore
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.shared.cache import MemoryCache

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DB_URL",
    "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend",
)
USER = "case-user"


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
        await connection.execute(text("TRUNCATE TABLE cases, case_counters RESTART IDENTITY CASCADE"))
        await connection.execute(
            text(
                "INSERT INTO users (id, username, role, password_hash) "
                "VALUES (:id, :id, 'user', 'x') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": USER},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, username, role, password_hash) "
                "VALUES ('guest-1', 'guest-1', 'guest', '') ON CONFLICT (id) DO NOTHING"
            )
        )
    store = PostgresCaseStore(engine)
    yield store, engine
    await engine.dispose()


def _service(store: PostgresCaseStore) -> CaseService:
    return CaseService(
        store=store,
        analysis=MemoryAnalysis(),
        jobs=MemoryJobs(),
        assignments=MemoryAssignments(),
        catalog=seed_catalog(),
        cache=MemoryCache(),
    )


async def _scalar(engine, statement: str, **params):
    async with engine.connect() as connection:
        return await connection.scalar(text(statement), params)


async def test_completed_case_is_a_row_and_a_guest_case_is_not_listed(database) -> None:
    store, engine = database
    service = _service(store)
    spec = CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12")
    case = await service.create(spec=spec, owner_id=USER, role="user")
    assert case.verdict is not None and case.verdict.code == "strong"
    assert await _scalar(engine, "SELECT verdict_code FROM cases WHERE id = :id", id=case.id) == "strong"
    assert await _scalar(engine, "SELECT result_hash FROM cases WHERE id = :id", id=case.id) == case.result_hash
    assert await _scalar(engine, "SELECT catalog_version FROM cases WHERE id = :id", id=case.id) == "catalog-v1"
    guest = await service.create(spec=spec, owner_id="guest-1", role="guest")
    assert guest.ephemeral is True
    assert await _scalar(engine, "SELECT ephemeral FROM cases WHERE id = :id", id=guest.id) is True
    assert await service.list_cases(actor_id="guest-1", role="guest") == []
    opened = await service.get(guest.id, actor_id="guest-1", role="guest")
    assert opened.id == guest.id
    assert await _scalar(engine, "SELECT count(*) FROM cases") == 2


async def test_migration_roundtrip_restores_the_case_tables(postgres_url: str) -> None:
    admin = _engine(postgres_url)
    async with admin.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_cases_mig"))
        await autocommit.execute(text("CREATE DATABASE earthtrend_cases_mig"))
    await admin.dispose()
    mig_url = postgres_url.rsplit("/", 1)[0] + "/earthtrend_cases_mig"
    sync_url = mig_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")
    probe = _engine(mig_url)

    async def table_count(name: str) -> int:
        async with probe.connect() as connection:
            found = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                ),
                {"name": name},
            )
        return int(found)

    assert await table_count("cases") == 1
    assert await table_count("case_counters") == 1
    command.downgrade(config, "005_jobs")
    assert await table_count("cases") == 0
    assert await table_count("jobs") == 1
    command.upgrade(config, "head")
    assert await table_count("cases") == 1
    await probe.dispose()
    async with _engine(postgres_url).connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_cases_mig"))
