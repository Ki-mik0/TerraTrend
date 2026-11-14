"""SQLAlchemy 2.0 async engine, session factory and the declarative base.

Alembic (``alembic/env.py``) reads ``Base.metadata``; table modules of the zones import
``Base`` from here and must be imported in ``earthtrend.api.infrastructure.models``.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import MetaData, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Stable constraint names so SQLite batch migrations can find and alter them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def ensure_sqlite_dir(db_url: str) -> None:
    """Create the parent folder of a file-based SQLite database (``data/`` on a fresh clone)."""
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def create_engine(db_url: str) -> AsyncEngine:
    ensure_sqlite_dir(db_url)
    return create_async_engine(db_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class SqlDatabaseProbe:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ping(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
