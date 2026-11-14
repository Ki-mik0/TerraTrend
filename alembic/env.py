"""Alembic environment: async SQLAlchemy, URL from settings (``DB_URL``), batch mode for SQLite.

Precedence of the database URL: ``-x db_url=...`` > ``DB_URL`` / ``.env`` > ``alembic.ini``.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from earthtrend.api.infrastructure.models import metadata
from earthtrend.api.infrastructure.shared.session import ensure_sqlite_dir
from earthtrend.api.settings import Settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def _db_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if "db_url" in x_args:
        return x_args["db_url"]
    if "DB_URL" in os.environ or os.path.exists(".env"):
        return Settings().db_url
    return config.get_main_option("sqlalchemy.url") or Settings().db_url


DB_URL = _db_url()
config.set_main_option("sqlalchemy.url", DB_URL)
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    ensure_sqlite_dir(DB_URL)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
