"""Wire identity with a memory store, or with PostgreSQL and an optional Redis cache."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.infrastructure.identity.cache import NullUserCache, redis_cache
from earthtrend.api.infrastructure.identity.clock import SystemClock
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword, JwtTokens
from earthtrend.api.infrastructure.identity.memory_store import MemoryIdentityStore
from earthtrend.api.infrastructure.identity.postgres import Base, PostgresIdentityStore


class MemoryCaseLookup:
    def __init__(self, cases: dict[str, Case] | None = None) -> None:
        self.cases = cases or {}

    async def get(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)


def build_identity_service(cases: MemoryCaseLookup | None = None) -> IdentityService:
    passwords = ArgonPassword()
    return IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=cases or MemoryCaseLookup(),
        store=MemoryIdentityStore(passwords=passwords, clock=SystemClock()),
        cache=NullUserCache(),
    )


def build_postgres_identity(
    url: str, redis_url: str | None = None, cases: MemoryCaseLookup | None = None
) -> tuple[IdentityService, object]:
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    passwords = ArgonPassword()
    service = IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=cases or MemoryCaseLookup(),
        store=PostgresIdentityStore(engine, passwords=passwords, clock=SystemClock()),
        cache=redis_cache(redis_url) if redis_url else NullUserCache(),
    )

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    return service, prepare


def identity_from_env() -> tuple[IdentityService, object | None]:
    url = os.environ.get("DB_URL", "")
    if url.startswith("postgresql"):
        return build_postgres_identity(url, os.environ.get("REDIS_URL") or None)
    from earthtrend.api.infrastructure.shared.snapshot import persist

    passwords = ArgonPassword()
    store = persist(
        MemoryIdentityStore(passwords=passwords, clock=SystemClock()),
        "identity",
        ("users", "audit", "reviews", "secret_hashes", "_counters"),
    )
    return IdentityService(passwords=passwords, tokens=JwtTokens(), cases=MemoryCaseLookup(), store=store, cache=NullUserCache()), None
