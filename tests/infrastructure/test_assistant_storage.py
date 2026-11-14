"""Assistant history in SQL (SQLite always, PostgreSQL when reachable) and the Redis cache and limiter."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.domain.assistant.exchange import AssistantExchange, ToolStep
from earthtrend.api.infrastructure.assistant import wiring
from earthtrend.api.infrastructure.assistant.cache import (
    AllowAllLimiter,
    NullPlanCache,
    RedisPlanCache,
    RedisRateLimiter,
    redis_client,
)
from earthtrend.api.infrastructure.shared.cache import reset_shared_redis, shared_redis
from earthtrend.api.infrastructure.assistant.memory import MemoryExchangeRepository, MemoryNotes
from earthtrend.api.infrastructure.assistant.narrator import TemplateNarrator
from earthtrend.api.infrastructure.assistant.postgres import AssistantBase, PostgresExchangeRepository

MOMENT = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
POSTGRES_URL = os.environ.get("DB_URL", "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend")


def _exchange(exchange_id: str, owner_id: str = "u1", minutes: int = 0) -> AssistantExchange:
    exchange = AssistantExchange(
        id=exchange_id,
        question="Чи сохне ґрунт?",
        language="uk",
        role="user",
        owner_id=owner_id,
        created_at=MOMENT + timedelta(minutes=minutes),
        steps=[ToolStep("analyze_case", "тренд", {"variable_id": "gldas_sm"})],
    )
    exchange.add_case("case_1")
    exchange.cite({"case_id": "case_1", "variable_id": "gldas_sm"})
    exchange.warn("case_required", tool="get_story")
    return exchange


async def _check_repository(repository: PostgresExchangeRepository) -> None:
    first = _exchange("ask_1")
    await repository.save(first)
    first.finish("Нахил 0.42.")
    await repository.save(first)
    await repository.save(_exchange("ask_2", minutes=5))
    await repository.save(_exchange("ask_3", owner_id="u2"))

    loaded = await repository.get("ask_1", owner_id="u1")
    assert loaded is not None
    assert (loaded.status, loaded.answer, loaded.case_ids) == ("answered", "Нахил 0.42.", ["case_1"])
    assert loaded.steps == first.steps
    assert loaded.citations == [{"case_id": "case_1", "variable_id": "gldas_sm"}]
    assert loaded.warnings == first.warnings
    assert await repository.get("ask_1", owner_id="u2") is None
    assert await repository.get("missing", owner_id="u1") is None
    assert [item.id for item in await repository.list(owner_id="u1", limit=10)] == ["ask_2", "ask_1"]
    assert [item.id for item in await repository.list(owner_id="u1", limit=1)] == ["ask_2"]


async def test_sql_repository_round_trip_on_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(AssistantBase.metadata.create_all)
    try:
        await _check_repository(PostgresExchangeRepository(engine))
    finally:
        await engine.dispose()


async def _reachable(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if not POSTGRES_URL.startswith("postgresql"):
        pytest.skip("DB_URL is not PostgreSQL")
    try:
        asyncio.run(_reachable(POSTGRES_URL))
    except Exception as error:
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    return POSTGRES_URL


async def test_postgres_repository_round_trip(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(AssistantBase.metadata.create_all)
        await connection.execute(text("TRUNCATE TABLE assistant_exchanges"))
    try:
        await _check_repository(PostgresExchangeRepository(engine))
    finally:
        await engine.dispose()


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.expiry[key] = ex or 0

    async def incr(self, key: str) -> int:
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def expire(self, key: str, seconds: int) -> None:
        self.expiry[key] = seconds


class DownRedis:
    async def get(self, key):
        raise RedisError("down")

    async def set(self, key, value, ex=None):
        raise RedisError("down")

    async def incr(self, key):
        raise RedisError("down")


async def test_redis_plan_cache_round_trip_and_ttl() -> None:
    client = FakeRedis()
    cache = RedisPlanCache(client, ttl_seconds=60)
    steps = [ToolStep("analyze_case", "тренд", {"variable_id": "gldas_sm"})]
    assert await cache.get("k") is None
    await cache.put("k", steps)
    assert await cache.get("k") == steps
    assert client.expiry["assistant:plan:k"] == 60
    client.values["assistant:plan:bad"] = "not json"
    client.values["assistant:plan:shape"] = '[{"tool": "x"}]'
    assert await cache.get("bad") is None
    assert await cache.get("shape") is None


async def test_redis_rate_limiter_counts_per_window() -> None:
    client = FakeRedis()
    clock = [0.0]
    limiter = RedisRateLimiter(client, limit=2, window_seconds=60, now=lambda: clock[0])
    assert [await limiter.allow("u1") for _ in range(3)] == [True, True, False]
    assert await limiter.allow("u2") is True
    assert client.expiry["assistant:rl:u1:0"] == 60
    clock[0] = 61.0
    assert await limiter.allow("u1") is True


async def test_redis_failure_is_a_miss_and_an_allow() -> None:
    cache = RedisPlanCache(DownRedis())
    assert await cache.get("k") is None
    await cache.put("k", [ToolStep("get_radar", "", {})])
    assert await RedisRateLimiter(DownRedis()).allow("u1") is True


async def test_null_adapters() -> None:
    assert await NullPlanCache().get("k") is None
    await NullPlanCache().put("k", [])
    assert await AllowAllLimiter().allow("u1") is True


def test_redis_client_is_the_shared_one_per_url() -> None:
    reset_shared_redis()
    try:
        client = redis_client("redis://127.0.0.1:6379/3")
        assert client.connection_pool.connection_kwargs["db"] == 3
        assert redis_client("redis://127.0.0.1:6379/3") is client is shared_redis("redis://127.0.0.1:6379/3")
    finally:
        reset_shared_redis()


async def test_memory_wiring_keeps_history_and_notes() -> None:
    notes = MemoryNotes()
    service = wiring.build_assistant_service(notes=notes, narrator=TemplateNarrator())
    exchange = await service.ask(question="Чи сохне ґрунт?", language="uk", role="user", owner_id="u1")
    assert notes.notes and (await service.history(owner_id="u1", role="user"))[0].id == exchange.id


def test_env_wiring_picks_adapters(monkeypatch) -> None:
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    service, prepare = wiring.assistant_from_env()
    assert prepare is None and isinstance(service._exchanges, MemoryExchangeRepository)

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    service, prepare = wiring.assistant_from_env()
    assert prepare is None
    assert isinstance(service._plans, RedisPlanCache) and isinstance(service._limiter, RedisRateLimiter)

    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/db")
    service, prepare = wiring.assistant_from_env()
    assert prepare is not None
    assert isinstance(service._exchanges, PostgresExchangeRepository)
    assert isinstance(service._plans, RedisPlanCache)

    monkeypatch.delenv("REDIS_URL")
    service, _ = wiring.assistant_from_env()
    assert isinstance(service._plans, NullPlanCache) and isinstance(service._limiter, AllowAllLimiter)


async def test_postgres_wiring_prepare_creates_the_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    service, prepare = wiring.build_postgres_assistant("unused", engine=engine, narrator=TemplateNarrator())
    try:
        await prepare()
        exchange = await service.ask(question="Чи сохне ґрунт?", language="uk", role="user", owner_id="u1")
        assert (await service.get(exchange.id, owner_id="u1")).status == "answered"
    finally:
        await engine.dispose()


REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/15")


async def _redis_or_skip():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except (RedisError, OSError) as error:
        await client.aclose()
        pytest.skip(f"Redis is not reachable: {error}")
    return client


async def test_real_redis_plan_cache_and_limiter() -> None:
    client = await _redis_or_skip()
    try:
        await client.delete("assistant:plan:test-key", "assistant:rl:test-actor:0")
        cache = RedisPlanCache(client, ttl_seconds=30)
        steps = [ToolStep("analyze_case", "тренд", {"variable_id": "gldas_sm", "season": "JJA"})]
        await cache.put("test-key", steps)
        assert await cache.get("test-key") == steps
        assert 0 < await client.ttl("assistant:plan:test-key") <= 30

        limiter = RedisRateLimiter(client, limit=2, window_seconds=60, now=lambda: 0.0)
        assert [await limiter.allow("test-actor") for _ in range(3)] == [True, True, False]
        assert 0 < await client.ttl("assistant:rl:test-actor:0") <= 60
    finally:
        await client.delete("assistant:plan:test-key", "assistant:rl:test-actor:0")
        await client.aclose()


async def test_full_stack_on_real_postgres_and_redis(postgres_url: str) -> None:
    client = await _redis_or_skip()
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    service, prepare = wiring.build_postgres_assistant(
        postgres_url, REDIS_URL, engine=engine, narrator=TemplateNarrator()
    )
    try:
        await prepare()
        exchange = await service.ask(question="Чи сохне ґрунт влітку?", language="uk", role="user", owner_id="it-user")
        stored = await service.get(exchange.id, owner_id="it-user")
        assert stored.status == "answered" and stored.case_ids == exchange.case_ids
        assert stored.answer == exchange.answer
        assert exchange.id in [item.id for item in await service.history(owner_id="it-user", role="user")]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM assistant_exchanges WHERE owner_id = 'it-user'"))
        await engine.dispose()
        await client.aclose()
        await shared_redis(REDIS_URL).aclose()
        reset_shared_redis()
