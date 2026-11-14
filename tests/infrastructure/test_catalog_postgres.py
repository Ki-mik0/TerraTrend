"""Catalog rows against a real PostgreSQL. Skipped when the database is down."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.catalog.postgres import PostgresCatalogStore
from earthtrend.api.infrastructure.catalog.wiring import catalog_from_env
from earthtrend.api.infrastructure.identity.postgres import Base

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DB_URL",
    "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend",
)


def _engine(url: str):
    return create_async_engine(url, poolclass=NullPool)


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if not str(DATABASE_URL).startswith("postgresql"):
        pytest.skip("PostgreSQL URL is not configured")
    return DATABASE_URL


@pytest.fixture
async def database(postgres_url: str):
    engine = _engine(postgres_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    "TRUNCATE TABLE custom_regions, catalog_passports, potential_feedback, cmr_queries"
                )
            )
    except Exception as error:
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    store = PostgresCatalogStore(engine)
    yield store, engine
    await engine.dispose()


async def _scalar(engine, statement: str, **params):
    async with engine.connect() as connection:
        return await connection.scalar(text(statement), params)


async def test_custom_region_and_feedback_survive_a_new_process(database, postgres_url: str, monkeypatch) -> None:
    store, engine = database
    monkeypatch.setenv("DB_URL", postgres_url)
    service, prepare = catalog_from_env()
    assert prepare is not None
    await prepare()
    region = await service.register_custom(name="Field", bbox=(30.0, 46.0, 32.0, 48.0), geometry=None)
    cases = build_case_service(feedback=service)
    case = await cases.create(spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"), owner_id="u1", role="user")
    await service.search_cmr("SMAP L-band 2015")
    again, _prepare = catalog_from_env()
    await again.load_overlay()
    loaded = await again.get_region(region.id)
    assert loaded.name == "Field"
    assert loaded.bbox == (30.0, 46.0, 32.0, 48.0)
    assert again.feedback[0].case_id == case.id
    assert again.feedback[0].actual_code == "strong"
    passport = await again.get_variable("smap_l_band_2015")
    assert passport.level == "cmr"
    await store.save_passport(passport)
    assert await _scalar(engine, "SELECT count(*) FROM custom_regions") == 1
    assert await _scalar(engine, "SELECT count(*) FROM catalog_passports") == 1
    assert await _scalar(engine, "SELECT count(*) FROM potential_feedback") == 1
    await store.save_query("cmr_9", "SMAP L-band 2015", passport.id)
    assert await _scalar(engine, "SELECT count(*) FROM cmr_queries") == 1
    names = await _scalar(
        engine,
        "SELECT string_agg(indexname, ',') FROM pg_indexes WHERE tablename IN ('custom_regions', 'cmr_queries')",
    )
    assert "custom_regions_kind" in names
    assert "cmr_queries_query" in names
    await again.reload(role="admin")
    assert await _scalar(engine, "SELECT count(*) FROM custom_regions") == 0
    assert await again.get_variable("smap_l_band_2015")


async def test_invalid_level_rolls_back(database) -> None:
    _store, engine = database
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO catalog_passports "
                    "(id, name, name_uk, kid_description, units, theme, domain, level, witnesses, doi) "
                    "VALUES ('bad', 'Bad', 'Погано', 'x', '1', 'cmr', 'cmr', 'nope', '[]'::jsonb, '')"
                )
            )
    assert await _scalar(engine, "SELECT count(*) FROM catalog_passports WHERE id = 'bad'") == 0


async def test_unreachable_database_writes_nothing(postgres_url: str) -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:1/earthtrend",
        poolclass=NullPool,
        connect_args={"timeout": 2},
    )
    store = PostgresCatalogStore(engine)
    service = seed_catalog()
    service.attach_store(store)
    with pytest.raises(Exception):
        await service.register_custom(name="Down", bbox=(0.0, 0.0, 1.0, 1.0), geometry=None)
    await engine.dispose()
    del postgres_url


async def test_migration_roundtrip_restores_catalog(postgres_url: str) -> None:
    admin = _engine(postgres_url)
    async with admin.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_catalog_mig"))
        await autocommit.execute(text("CREATE DATABASE earthtrend_catalog_mig"))
    await admin.dispose()
    mig_url = postgres_url.rsplit("/", 1)[0] + "/earthtrend_catalog_mig"
    sync_url = mig_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")
    command.downgrade(config, "006_cases")
    probe = _engine(mig_url)
    async with probe.connect() as connection:
        gone = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'custom_regions'"
            )
        )
    assert gone == 0
    command.upgrade(config, "head")
    async with probe.connect() as connection:
        back = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'catalog_passports'"
            )
        )
    assert back == 1
    await probe.dispose()
    async with _engine(postgres_url).connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_catalog_mig"))
