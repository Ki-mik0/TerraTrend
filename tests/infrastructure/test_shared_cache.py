from pathlib import Path

import pytest
from redis.exceptions import RedisError

from earthtrend.api.application.cache.service import CacheAdmin, CacheError, FamilyStats
from earthtrend.api.infrastructure.shared import cache as cache_module
from earthtrend.api.infrastructure.shared.cache import MemoryCache, MeteredCache, RedisCache, shared_redis
from earthtrend.api.infrastructure.shared.metrics import CACHE_ERRORS, CACHE_HITS, CACHE_MISSES, counter_value, family_of
from earthtrend.api.infrastructure.shared.storage import LocalObjectStorage, StorageError


class _FakeRedis:
    def __init__(self, broken: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.broken = broken

    def _check(self) -> None:
        if self.broken:
            raise RedisError("down")

    async def get(self, key):
        self._check()
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self._check()
        self.data[key] = value

    async def delete(self, *keys):
        self._check()
        return sum(1 for key in keys if self.data.pop(key, None) is not None)

    async def scan_iter(self, match, count):
        self._check()
        prefix = match.rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix):
                yield key

    async def ping(self):
        self._check()
        return True


async def test_delete_prefix_memory_and_redis(monkeypatch) -> None:
    memory = MemoryCache()
    for key in ("radar:a", "radar:b", "edu:c"):
        await memory.set_json(key, 1, ttl=60)
    assert await memory.delete_prefix("radar:") == 2
    assert await memory.get_json("edu:c") == 1 and await memory.ping()

    fake = _FakeRedis()
    redis = RedisCache(fake)
    for index in range(cache_module.SCAN_BATCH + 3):
        await redis.set_json(f"tile:{index}", index, ttl=60)
    await redis.set_json("edu:x", 1, ttl=60)
    assert await redis.delete_prefix("tile:") == cache_module.SCAN_BATCH + 3
    assert list(fake.data) == ["edu:x"] and await redis.ping()

    broken = RedisCache(_FakeRedis(broken=True))
    assert await broken.delete_prefix("tile:") == 0
    assert await broken.ping() is False
    assert broken.failures == 1


async def test_metered_cache_counts_per_family() -> None:
    metered = MeteredCache(MemoryCache())
    hits, misses = counter_value(CACHE_HITS, family="probe"), counter_value(CACHE_MISSES, family="probe")
    assert await metered.get_json("probe:k") is None
    await metered.set_json("probe:k", {"v": 1}, ttl=60)
    assert await metered.get_json("probe:k") == {"v": 1}
    assert counter_value(CACHE_HITS, family="probe") == hits + 1
    assert counter_value(CACHE_MISSES, family="probe") == misses + 1
    await metered.delete("probe:k")
    assert await metered.delete_prefix("probe:") == 0 and await metered.ping()

    errors = counter_value(CACHE_ERRORS, family="probe")
    failing = MeteredCache(RedisCache(_FakeRedis(broken=True)))
    assert await failing.get_json("probe:k") is None
    assert counter_value(CACHE_ERRORS, family="probe") == errors + 1
    assert family_of("tile/v1/x.png") == "tile" and family_of("plain") == "other"


def test_shared_redis_client_is_one_per_url(monkeypatch) -> None:
    assert shared_redis("redis://127.0.0.1:1/0") is shared_redis("redis://127.0.0.1:1/0")
    before = shared_redis("redis://127.0.0.1:1/0")
    cache_module.reset_shared_redis()
    assert shared_redis("redis://127.0.0.1:1/0") is not before
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    first, second = cache_module.cache_from_env(), cache_module.cache_from_env()
    assert first.inner._client is second.inner._client
    monkeypatch.delenv("REDIS_URL")
    assert isinstance(cache_module.cache_from_env().inner, MemoryCache)


async def test_local_storage_round_trip_and_safety(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    assert await storage.get("tile/a/b.png") is None
    await storage.put("tile/a/b.png", b"png")
    await storage.put("tile/a/c.png", b"png")
    assert await storage.get("tile/a/b.png") == b"png"
    assert not list(tmp_path.rglob(".tmp-*"))
    assert await storage.delete_prefix("tile/a/c.png") == 1
    assert await storage.delete_prefix("tile/") == 1
    assert await storage.delete_prefix("tile/") == 0
    assert await storage.ping()
    for bad in ("../escape", "/abs", "a//b", "a\\b", ""):
        with pytest.raises(StorageError):
            await storage.put(bad, b"x")


async def test_cache_admin_rules() -> None:
    audit: list[tuple[str, str]] = []

    class _Audit:
        async def record_admin(self, *, actor_id, role, action, subject_id):
            audit.append((action, subject_id))

    async def broken() -> int:
        raise RuntimeError("down")

    async def fine() -> int:
        return 3

    admin = CacheAdmin(
        cache=MeteredCache(MemoryCache()),
        storage=LocalObjectStorage(Path("unused-root")),
        audit=_Audit(),
        warmers={"ok": fine, "bad": broken},
        stats=lambda: {"edu": FamilyStats(hits=0, misses=0, errors=0)},
        backend="memory",
    )
    report = await admin.warm(actor_id="root", role="admin")
    assert report.warmed == {"ok": 3} and report.failed == {"bad": "RuntimeError"}
    backend, reachable, stats = await admin.stats(actor_id="root", role="admin")
    assert backend == "memory" and reachable and stats["edu"].hit_ratio is None
    assert FamilyStats(hits=3, misses=1, errors=0).hit_ratio == 0.75
    with pytest.raises(CacheError):
        await admin.clear("edu", actor_id="u", role="user")
    assert audit == [("warm_cache", "all")]
