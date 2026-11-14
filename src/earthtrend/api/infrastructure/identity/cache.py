"""Cache the session user. A Redis failure is a miss, not an outage."""

from __future__ import annotations

import json

from redis.asyncio import Redis
from redis.exceptions import RedisError

from earthtrend.api.domain.identity.model import User

_PREFIX = "identity:user:"
_TTL_SECONDS = 60


class NullUserCache:
    async def get(self, user_id: str) -> User | None:
        del user_id
        return None

    async def put(self, user: User) -> None:
        del user


class RedisUserCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, user_id: str) -> User | None:
        try:
            raw = await self._client.get(f"{_PREFIX}{user_id}")
        except RedisError:
            return None
        if raw is None:
            return None
        payload = json.loads(raw)
        return User(id=payload["id"], username=payload["username"], role=payload["role"], password_hash="")

    async def put(self, user: User) -> None:
        body = json.dumps({"id": user.id, "username": user.username, "role": user.role})
        try:
            await self._client.set(f"{_PREFIX}{user.id}", body, ex=_TTL_SECONDS)
        except RedisError:
            return


def redis_cache(url: str) -> RedisUserCache:
    return RedisUserCache(Redis.from_url(url, decode_responses=True))
