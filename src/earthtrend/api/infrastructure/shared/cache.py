"""Cache adapters: Redis for deployments, a TTL dict for tests and local runs.

A Redis failure is a miss, not an outage: callers fall back to the source of truth.
One Redis client is shared by every zone of the process. `cache_from_env()` wraps the adapter
in `MeteredCache`, which counts hits and misses per key family for `/metrics`.
"""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from earthtrend.api.infrastructure.shared.metrics import CACHE_ERRORS, CACHE_HITS, CACHE_MISSES, family_of

SCAN_BATCH = 500


class MemoryCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, tuple[float, str]] = {}

    async def get_json(self, key: str) -> Any | None:
        found = self._items.get(key)
        if found is None:
            return None
        expires, raw = found
        if expires <= self._clock():
            del self._items[key]
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        self._items[key] = (self._clock() + ttl, json.dumps(value, ensure_ascii=False))

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._items.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        doomed = [key for key in self._items if key.startswith(prefix)]
        for key in doomed:
            del self._items[key]
        return len(doomed)

    async def ping(self) -> bool:
        return True


class RedisCache:
    def __init__(self, client: Redis) -> None:
        self._client = client
        self.failures = 0

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
        except RedisError:
            self.failures += 1
            return None
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except RedisError:
            self.failures += 1

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            await self._client.delete(*keys)
        except RedisError:
            self.failures += 1

    async def delete_prefix(self, prefix: str) -> int:
        removed = 0
        try:
            batch: list[str] = []
            async for key in self._client.scan_iter(match=f"{prefix}*", count=SCAN_BATCH):
                batch.append(key)
                if len(batch) >= SCAN_BATCH:
                    removed += await self._client.delete(*batch)
                    batch = []
            if batch:
                removed += await self._client.delete(*batch)
        except RedisError:
            self.failures += 1
        return removed

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False


class MeteredCache:
    """Counts hits, misses and failures per family. Behaves exactly like the wrapped cache."""

    def __init__(self, inner: MemoryCache | RedisCache) -> None:
        self.inner = inner

    async def get_json(self, key: str) -> Any | None:
        family = family_of(key)
        failures = getattr(self.inner, "failures", 0)
        value = await self.inner.get_json(key)
        if getattr(self.inner, "failures", 0) > failures:
            CACHE_ERRORS.labels(family=family).inc()
        (CACHE_MISSES if value is None else CACHE_HITS).labels(family=family).inc()
        return value

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self.inner.set_json(key, value, ttl)

    async def delete(self, *keys: str) -> None:
        await self.inner.delete(*keys)

    async def delete_prefix(self, prefix: str) -> int:
        return await self.inner.delete_prefix(prefix)

    async def ping(self) -> bool:
        return await self.inner.ping()


@functools.cache
def shared_redis(url: str) -> Redis:
    """One client and one connection pool per Redis URL for the whole process.

    An asyncio client belongs to the event loop that first used it. The server runs one loop;
    code that starts several loops (tests, scripts) calls `reset_shared_redis()` between them.
    """
    return Redis.from_url(url, decode_responses=True)


def reset_shared_redis() -> None:
    """Forget the shared clients, e.g. before a new event loop starts."""
    shared_redis.cache_clear()


def cache_from_env() -> MeteredCache:
    url = os.environ.get("REDIS_URL")
    if url:
        return MeteredCache(RedisCache(shared_redis(url)))
    return MeteredCache(MemoryCache())
