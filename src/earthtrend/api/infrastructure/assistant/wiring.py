"""Wire the assistant with memory adapters, or with PostgreSQL history and a Redis plan cache and limiter."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earthtrend.api.application.assistant.ports import NarratorPort, NotePort
from earthtrend.api.application.assistant.service import AssistantService
from earthtrend.api.infrastructure.assistant.cache import (
    AllowAllLimiter,
    NullPlanCache,
    RedisPlanCache,
    RedisRateLimiter,
    redis_client,
)
from earthtrend.api.infrastructure.assistant.memory import (
    MemoryCases,
    MemoryCatalog,
    MemoryEvidence,
    MemoryExchangeRepository,
    MemoryNotes,
    MemoryPlanCache,
    MemoryProfile,
    MemoryRadar,
    MemoryRateLimiter,
    MemoryStory,
    MemoryUrban,
)
from earthtrend.api.infrastructure.assistant.narrator import narrator_from_env
from earthtrend.api.infrastructure.assistant.postgres import AssistantBase, PostgresExchangeRepository

Prepare = Callable[[], Awaitable[None]]


@dataclass
class Neighbors:
    """Adapters to the other slices. Default to in-memory stand-ins."""

    catalog: Any = None
    cases: Any = None
    evidence: Any = None
    story: Any = None
    profile: Any = None
    urban: Any = None
    radar: Any = None
    notes: NotePort | None = None


def _service(neighbors: Neighbors, narrator: NarratorPort | None, **storage: Any) -> AssistantService:
    return AssistantService(
        catalog=neighbors.catalog or MemoryCatalog(),
        cases=neighbors.cases or MemoryCases(),
        evidence=neighbors.evidence or MemoryEvidence(),
        story=neighbors.story or MemoryStory(),
        profile=neighbors.profile or MemoryProfile(),
        urban=neighbors.urban or MemoryUrban(),
        radar=neighbors.radar or MemoryRadar(),
        notes=neighbors.notes if neighbors.notes is not None else MemoryNotes(),
        narrator=narrator or narrator_from_env(),
        **storage,
    )


def build_assistant_service(
    notes: MemoryNotes | None = None,
    neighbors: Neighbors | None = None,
    narrator: NarratorPort | None = None,
) -> AssistantService:
    chosen = neighbors or Neighbors()
    if notes is not None:
        chosen.notes = notes
    return _service(
        chosen,
        narrator,
        exchanges=MemoryExchangeRepository(),
        plans=MemoryPlanCache(),
        limiter=MemoryRateLimiter(),
    )


def build_postgres_assistant(
    url: str,
    redis_url: str | None = None,
    neighbors: Neighbors | None = None,
    narrator: NarratorPort | None = None,
    engine: AsyncEngine | None = None,
) -> tuple[AssistantService, Prepare]:
    engine = engine or create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    if redis_url:
        client = redis_client(redis_url)
        plans: Any = RedisPlanCache(client)
        limiter: Any = RedisRateLimiter(client)
    else:
        plans, limiter = NullPlanCache(), AllowAllLimiter()
    service = _service(
        neighbors or Neighbors(),
        narrator,
        exchanges=PostgresExchangeRepository(engine),
        plans=plans,
        limiter=limiter,
    )

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(AssistantBase.metadata.create_all)

    return service, prepare


def assistant_from_env(neighbors: Neighbors | None = None) -> tuple[AssistantService, Prepare | None]:
    url = os.environ.get("DB_URL", "")
    redis_url = os.environ.get("REDIS_URL") or None
    if url.startswith("postgresql"):
        return build_postgres_assistant(url, redis_url, neighbors)
    if redis_url:
        client = redis_client(redis_url)
        service = _service(
            neighbors or Neighbors(),
            None,
            exchanges=MemoryExchangeRepository(),
            plans=RedisPlanCache(client),
            limiter=RedisRateLimiter(client),
        )
        return service, None
    return build_assistant_service(neighbors=neighbors), None
