"""Redis plan cache and rate limiter. A Redis failure is a miss or an allow, never an outage."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from earthtrend.api.domain.assistant.exchange import ToolStep
from earthtrend.api.infrastructure.shared.cache import shared_redis

PLAN_PREFIX = "assistant:plan:"
RATE_PREFIX = "assistant:rl:"
PLAN_TTL_SECONDS = 3600


class NullPlanCache:
    async def get(self, key: str) -> list[ToolStep] | None:
        del key
        return None

    async def put(self, key: str, steps: list[ToolStep]) -> None:
        del key, steps


class AllowAllLimiter:
    async def allow(self, actor_id: str) -> bool:
        del actor_id
        return True


class RedisPlanCache:
    def __init__(self, client: Any, ttl_seconds: int = PLAN_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl_seconds

    async def get(self, key: str) -> list[ToolStep] | None:
        try:
            raw = await self._client.get(f"{PLAN_PREFIX}{key}")
        except RedisError:
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return [ToolStep(tool=item["tool"], reason=item["reason"], input=item["input"]) for item in payload]
        except (ValueError, KeyError, TypeError):
            return None

    async def put(self, key: str, steps: list[ToolStep]) -> None:
        body = json.dumps([step.payload() for step in steps], ensure_ascii=False)
        try:
            await self._client.set(f"{PLAN_PREFIX}{key}", body, ex=self._ttl)
        except RedisError:
            return


class RedisRateLimiter:
    """Fixed window: INCR a per-actor, per-window key and expire it with the window."""

    def __init__(
        self, client: Any, limit: int = 20, window_seconds: int = 60, now: Callable[[], float] = time.time
    ) -> None:
        self._client = client
        self._limit = limit
        self._window = window_seconds
        self._now = now

    async def allow(self, actor_id: str) -> bool:
        key = f"{RATE_PREFIX}{actor_id}:{int(self._now()) // self._window}"
        try:
            count = await self._client.incr(key)
            if count == 1:
                await self._client.expire(key, self._window)
        except RedisError:
            return True
        return int(count) <= self._limit


def redis_client(url: str) -> Redis:
    """The app-wide client for this URL, so the assistant shares one connection pool with the other caches."""
    return shared_redis(url)
