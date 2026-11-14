"""Wire the journal to memory, or to PostgreSQL when DB_URL points there."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.journal.service import CaseLookup, JournalService
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.journal.memory import MemoryJournalStore
from earthtrend.api.infrastructure.journal.postgres import PostgresJournalStore


def build_journal_service(cases: CaseLookup) -> JournalService:
    return JournalService(cases=cases, store=MemoryJournalStore())


def build_postgres_journal(url: str, cases: CaseLookup) -> tuple[JournalService, object]:
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    service = JournalService(cases=cases, store=PostgresJournalStore(engine))

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    return service, prepare


def journal_from_env(cases: CaseLookup) -> tuple[JournalService, object | None]:
    url = os.environ.get("DB_URL", "")
    if url.startswith("postgresql"):
        return build_postgres_journal(url, cases)
    return build_journal_service(cases), None
