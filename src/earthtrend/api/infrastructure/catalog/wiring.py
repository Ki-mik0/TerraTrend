"""Wire the catalog to memory, and to PostgreSQL when DB_URL points there."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.catalog.pool import ProcessCmr
from earthtrend.api.infrastructure.catalog.postgres import PostgresCatalogStore
from earthtrend.api.infrastructure.identity.postgres import Base
from earthtrend.api.infrastructure.shared.cache import cache_from_env


def catalog_from_env(cache=None) -> tuple[CatalogService, object | None]:
    service = seed_catalog(cache=cache if cache is not None else cache_from_env())
    url = os.environ.get("DB_URL", "")
    if not url.startswith("postgresql"):
        return service, None
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    service.attach_store(PostgresCatalogStore(engine))
    service.attach_runner(ProcessCmr())

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await service.load_overlay()

    return service, prepare
