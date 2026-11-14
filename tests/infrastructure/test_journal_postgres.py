"""Journal against a real PostgreSQL. Skipped when the database is down."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.application.journal.service import JournalService
from earthtrend.api.domain.cases.model import Case, CaseSpec
from earthtrend.api.domain.journal.model import JournalError
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.journal.postgres import NoteRow, PostgresJournalStore, SavedCaseRow
from earthtrend.api.infrastructure.journal.wiring import journal_from_env

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DB_URL",
    "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend",
)
USER = "journal-user"


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
        await connection.execute(text("TRUNCATE TABLE notes, saved_cases, journal_counters RESTART IDENTITY CASCADE"))
        await connection.execute(
            text(
                "INSERT INTO users (id, username, role, password_hash) "
                "VALUES (:id, :id, 'user', 'x') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": USER},
        )
    store = PostgresJournalStore(engine)
    yield store, engine
    await engine.dispose()


class _Cases:
    def __init__(self, case: Case) -> None:
        self.case = case

    async def get(self, case_id: str) -> Case | None:
        return self.case if self.case.id == case_id else None


def _service(store: PostgresJournalStore) -> JournalService:
    case = Case(
        id="case_1",
        owner_id=USER,
        role="user",
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"),
    )
    return JournalService(cases=_Cases(case), store=store)


async def _scalar(engine, statement: str, **params):
    async with engine.connect() as connection:
        return await connection.scalar(text(statement), params)


async def test_hypothesis_and_saved_case_are_rows(database) -> None:
    store, engine = database
    service = _service(store)
    await service.remember(owner_id=USER, case_id="case_1", ephemeral=False)
    note = await service.add_note(
        author_id=USER, role="user", case_id="case_1", text="літо сохне", kind="hypothesis"
    )
    assert note.kind == "hypothesis"
    assert await _scalar(engine, "SELECT kind FROM notes WHERE id = :id", id=note.id) == "hypothesis"
    assert await _scalar(engine, "SELECT text FROM notes WHERE id = :id", id=note.id) == "літо сохне"
    assert await _scalar(engine, "SELECT count(*) FROM saved_cases WHERE owner_id = :owner", owner=USER) == 1
    listed, saved = await service.list_journal(actor_id=USER)
    assert [item.id for item in listed] == [note.id]
    assert [item.case_id for item in saved] == ["case_1"]
    with pytest.raises(JournalError) as missing:
        await service.delete_note("missing", actor_id=USER)
    assert missing.value.code == "note_not_found"
    with pytest.raises(JournalError) as hidden:
        await service.delete_note(note.id, actor_id="stranger")
    assert hidden.value.code == "note_not_found"
    assert await _scalar(engine, "SELECT count(*) FROM notes") == 1
    await service.delete_note(note.id, actor_id=USER)
    assert await _scalar(engine, "SELECT count(*) FROM notes") == 0
    assert await _scalar(engine, "SELECT count(*) FROM saved_cases") == 1
    again = await service.add_note(author_id=USER, role="user", case_id="case_1", text="ще", kind="note")
    assert again.id != note.id
    assert await _scalar(engine, "SELECT kind FROM notes WHERE id = :id", id=again.id) == "note"


async def test_second_remember_keeps_one_saved_case(database) -> None:
    store, engine = database
    service = _service(store)
    await service.remember(owner_id=USER, case_id="case_1", ephemeral=False)
    await service.remember(owner_id=USER, case_id="case_1", ephemeral=False)
    await asyncio.gather(
        service.remember(owner_id=USER, case_id="case_1", ephemeral=False),
        service.remember(owner_id=USER, case_id="case_1", ephemeral=False),
    )
    assert await _scalar(engine, "SELECT count(*) FROM saved_cases") == 1
    await service.remember(owner_id=USER, case_id="case_1", ephemeral=True)
    assert await _scalar(engine, "SELECT count(*) FROM saved_cases") == 1


async def test_bad_kind_rolls_back_the_saved_case(database) -> None:
    store, engine = database
    with pytest.raises(IntegrityError):
        async with store._sessions() as session:
            async with session.begin():
                session.add(SavedCaseRow(owner_id=USER, case_id="case_1"))
                session.add(
                    NoteRow(id="note_x", author_id=USER, case_id="case_1", kind="nope", text="x")
                )
    assert await _scalar(engine, "SELECT count(*) FROM notes") == 0
    assert await _scalar(engine, "SELECT count(*) FROM saved_cases") == 0


async def test_migration_roundtrip_restores_the_journal_tables(postgres_url: str) -> None:
    admin = _engine(postgres_url)
    async with admin.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_journal_mig"))
        await autocommit.execute(text("CREATE DATABASE earthtrend_journal_mig"))
    await admin.dispose()
    mig_url = postgres_url.rsplit("/", 1)[0] + "/earthtrend_journal_mig"
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

    assert await table_count("notes") == 1
    assert await table_count("saved_cases") == 1
    command.downgrade(config, "003_assistant")
    assert await table_count("notes") == 0
    assert await table_count("users") == 1
    command.upgrade(config, "head")
    assert await table_count("notes") == 1
    await probe.dispose()
    async with _engine(postgres_url).connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_journal_mig"))


async def test_env_builder_prepares_the_journal_tables(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL", postgres_url)
    case = Case(
        id="case_1",
        owner_id=USER,
        role="user",
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"),
    )
    service, prepare = journal_from_env(_Cases(case))
    assert prepare is not None
    await prepare()
    await service._store.engine.dispose()
