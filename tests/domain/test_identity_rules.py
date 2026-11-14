"""Identity rules that do not need PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from earthtrend.api.domain.cases.model import AiOpinion, Case, CaseSpec
from earthtrend.api.domain.identity.model import IdentityError, User
from earthtrend.api.infrastructure.identity.cache import RedisUserCache
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword, JwtTokens
from earthtrend.api.infrastructure.identity.memory_store import MemoryIdentityStore
from earthtrend.api.infrastructure.identity.wiring import MemoryCaseLookup, build_identity_service
from earthtrend.api.application.identity.service import IdentityService


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, User] = {}

    async def get(self, user_id: str) -> User | None:
        return self.data.get(user_id)

    async def put(self, user: User) -> None:
        self.data[user.id] = User(id=user.id, username=user.username, role=user.role, password_hash="")


class DownCache:
    async def get(self, user_id: str) -> User | None:
        raise ConnectionError(user_id)

    async def put(self, user: User) -> None:
        raise ConnectionError(user.id)


class CountingStore:
    def __init__(self, inner: MemoryIdentityStore) -> None:
        self.inner = inner
        self.reads = 0
        self.audit = inner.audit

    async def get_by_id(self, user_id: str):
        self.reads += 1
        return await self.inner.get_by_id(user_id)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def _case(disagrees: bool) -> Case:
    return Case(
        id="split",
        owner_id="u1",
        role="user",
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"),
        ai_opinion=AiOpinion(predicted_class="step", confidence="high", disagrees=disagrees),
    )


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(IdentityError) as caught:
        User(id="u", username="u", role="student", password_hash="x")
    assert caught.value.code == "role_invalid"


def test_duplicate_username_and_second_login_keep_one_user() -> None:
    service = build_identity_service()

    async def scenario() -> None:
        await service.add_user(user_id="u1", username="ada", role="user", password="secret")
        with pytest.raises(IdentityError) as caught:
            await service.add_user(user_id="u2", username="ada", role="admin", password="other")
        assert caught.value.code == "username_taken"
        await service.login(username="ada", password="secret")
        await service.login(username="ada", password="secret")
        assert len(service._store.users) == 1
        assert service._store.users["u1"].role == "user"

    asyncio.run(scenario())


def test_key_secret_is_stored_as_a_hash_and_second_revoke_does_not_audit() -> None:
    moment = datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)
    passwords = ArgonPassword()
    store = MemoryIdentityStore(passwords=passwords, clock=FixedClock(moment))
    service = IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=MemoryCaseLookup(),
        store=store,
    )

    async def scenario() -> None:
        await service.add_user(user_id="admin", username="ada", role="admin", password="secret")
        key = await service.issue_key(actor_id="admin", role="admin", owner_id="admin")
        assert store.secret_hashes[key.id] != key.secret
        assert store.secret_hashes[key.id].startswith("$argon2")
        assert service.audit[0].created_at == moment
        await service.revoke_key(actor_id="admin", role="admin", key_id=key.id)
        with pytest.raises(IdentityError) as caught:
            await service.revoke_key(actor_id="admin", role="admin", key_id=key.id)
        assert caught.value.code == "key_not_found"
        assert [item.action for item in service.audit] == ["issue_key", "revoke_key"]

    asyncio.run(scenario())


def test_empty_note_does_not_create_a_review() -> None:
    passwords = ArgonPassword()
    store = MemoryIdentityStore(passwords=passwords, clock=FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc)))
    service = IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=MemoryCaseLookup({"split": _case(True)}),
        store=store,
    )

    async def scenario() -> None:
        await service.add_user(user_id="admin", username="ada", role="admin", password="secret")
        with pytest.raises(IdentityError) as caught:
            await service.review(actor_id="admin", role="admin", case_id="split", note="  ")
        assert caught.value.code == "note_empty"
        assert service.reviews == []
        assert service.audit == []

    asyncio.run(scenario())


def test_removed_user_token_is_rejected_and_a_dead_cache_falls_back() -> None:
    passwords = ArgonPassword()
    inner = MemoryIdentityStore(passwords=passwords, clock=FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc)))
    store = CountingStore(inner)
    service = IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=MemoryCaseLookup(),
        store=store,
        cache=DownCache(),
    )

    async def scenario() -> None:
        await service.add_user(user_id="u1", username="ada", role="user", password="secret")
        token = await service.login(username="ada", password="secret")
        assert await service.read_session(token) == ("u1", "user")
        assert store.reads == 1
        del inner.users["u1"]
        with pytest.raises(IdentityError) as caught:
            await service.read_session(token)
        assert caught.value.code == "invalid_token"

    asyncio.run(scenario())


def test_warm_cache_serves_the_second_session_read() -> None:
    passwords = ArgonPassword()
    inner = MemoryIdentityStore(passwords=passwords, clock=FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc)))
    store = CountingStore(inner)
    service = IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=MemoryCaseLookup(),
        store=store,
        cache=DictCache(),
    )

    async def scenario() -> None:
        await service.add_user(user_id="u1", username="ada", role="user", password="secret")
        token = await service.login(username="ada", password="secret")
        await service.read_session(token)
        await service.read_session(token)
        assert store.reads == 0

    asyncio.run(scenario())


def test_redis_cache_roundtrip_and_outage_are_a_miss() -> None:
    class FakeRedis:
        def __init__(self, fail: bool) -> None:
            self.fail = fail
            self.data: dict[str, str] = {}

        async def get(self, key: str):
            if self.fail:
                from redis.exceptions import RedisError

                raise RedisError("down")
            return self.data.get(key)

        async def set(self, key: str, value: str, ex: int | None = None):
            if self.fail:
                from redis.exceptions import RedisError

                raise RedisError("down")
            self.data[key] = value
            assert ex == 60

    async def scenario() -> None:
        cache = RedisUserCache(FakeRedis(False))
        user = User(id="u1", username="ada", role="admin", password_hash="hidden")
        await cache.put(user)
        found = await cache.get("u1")
        assert found is not None
        assert found.role == "admin"
        assert found.password_hash == ""
        down = RedisUserCache(FakeRedis(True))
        await down.put(user)
        assert await down.get("u1") is None
        from earthtrend.api.infrastructure.identity.cache import redis_cache

        built = redis_cache("redis://127.0.0.1:6379/0")
        await built._client.aclose()

    asyncio.run(scenario())
