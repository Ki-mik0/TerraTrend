from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import earthtrend.api.infrastructure.cases.postgres  # noqa: F401  registers case tables
import earthtrend.api.infrastructure.journal.postgres  # noqa: F401  registers journal tables
from earthtrend.api.infrastructure.assistant.postgres import AssistantBase
from earthtrend.api.infrastructure.education.sql import Base as EducationBase
from earthtrend.api.infrastructure.identity.postgres import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = [Base.metadata, EducationBase.metadata, AssistantBase.metadata]


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
