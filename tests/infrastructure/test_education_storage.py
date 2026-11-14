import pytest
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.domain.education.model import Assignment, Badge, DemoProgress, ShareLink, Submission
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.education import wiring
from earthtrend.api.infrastructure.education.memory import MemoryEducationStore
from earthtrend.api.infrastructure.education.sql import SqlEducationStore
from earthtrend.api.infrastructure.education.wiring import build_education_service
from earthtrend.api.infrastructure.shared import cache as cache_module
from earthtrend.api.infrastructure.shared.cache import MemoryCache, RedisCache


@pytest.fixture(params=["memory", "sql"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryEducationStore()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'edu.db'}")
    sql = SqlEducationStore(engine)
    await sql.prepare()
    yield sql
    await engine.dispose()


async def test_store_round_trip(store) -> None:
    assignment = Assignment(id="a1", teacher_id="t1", title="Soil", student_ids=("s1",), case_ids=("c1", "c2"))
    await store.save_assignment(assignment)
    assignment.share = ShareLink(token="tok")
    assignment.student_ids = ("s1", "s2")
    await store.save_assignment(assignment)
    await store.save_assignment(Assignment(id="a2", teacher_id="t2", title="Other", student_ids=(), case_ids=()))

    found = await store.find_by_token("tok")
    assert found is not None and found.student_ids == ("s1", "s2") and found.case_ids == ("c1", "c2")
    assert await store.find_by_token("missing") is None
    assert await store.get_assignment("missing") is None
    assert [item.id for item in await store.list_assignments("s2")] == ["a1"]
    assert [item.id for item in await store.list_assignments("t2")] == ["a2"]
    assert len(await store.list_assignments(None)) == 2

    await store.add_submission(Submission(id="sub1", assignment_id="a1", student_id="s1", case_id="c1", text="x"))
    assert [item.id for item in await store.list_submissions(["a1"])] == ["sub1"]
    assert await store.list_submissions([]) == []
    loaded = await store.get_assignment("a1")
    assert [item.id for item in loaded.submissions] == ["sub1"]

    assert await store.add_badge(Badge(id="b1", user_id="s1", code="found_split", reason="c1")) is True
    assert await store.add_badge(Badge(id="b2", user_id="s1", code="found_split", reason="c2")) is False
    assert await store.add_badge(Badge(id="b3", user_id="s1", code="demo", reason="d1")) is True
    assert sorted(item.code for item in await store.list_badges("s1")) == ["demo", "found_split"]

    assert await store.get_progress("s1", "d1") is None
    await store.save_progress(DemoProgress(user_id="s1", demo_id="d1", steps_done={2, 1}))
    progress = await store.get_progress("s1", "d1")
    assert progress.steps_done == {1, 2}

    await store.record_quiz(user_id="s1", quiz_id="q1", correct=True)


async def test_memory_cache_expires() -> None:
    now = [0.0]
    cache = MemoryCache(clock=lambda: now[0])
    await cache.set_json("k", {"a": 1}, ttl=10)
    assert await cache.get_json("k") == {"a": 1}
    now[0] = 11
    assert await cache.get_json("k") is None
    await cache.set_json("k", [1], ttl=10)
    await cache.delete("k", "other")
    assert await cache.get_json("k") is None


class _FakeRedis:
    def __init__(self, broken: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.broken = broken

    async def get(self, key):
        if self.broken:
            raise RedisError("down")
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        if self.broken:
            raise RedisError("down")
        self.data[key] = value

    async def delete(self, *keys):
        if self.broken:
            raise RedisError("down")
        for key in keys:
            self.data.pop(key, None)


async def test_redis_cache_round_trip_and_outage_is_a_miss() -> None:
    healthy = RedisCache(_FakeRedis())
    await healthy.set_json("k", {"t": "тренд"}, ttl=5)
    assert await healthy.get_json("k") == {"t": "тренд"}
    await healthy.delete("k")
    await healthy.delete()
    assert await healthy.get_json("k") is None

    broken = RedisCache(_FakeRedis(broken=True))
    await broken.set_json("k", 1, ttl=5)
    await broken.delete("k")
    assert await broken.get_json("k") is None


def test_cache_and_store_from_env(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(cache_module.cache_from_env().inner, MemoryCache)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert isinstance(cache_module.cache_from_env().inner, RedisCache)

    monkeypatch.delenv("REDIS_URL")
    monkeypatch.setenv("DB_URL", "")
    service, prepare = wiring.education_from_env(lessons=seed_catalog())
    assert prepare is None and service is not None

    monkeypatch.setattr(wiring, "create_async_engine", lambda url, **_: create_async_engine("sqlite+aiosqlite://"))
    monkeypatch.setenv("DB_URL", "postgresql+psycopg://u:p@db/x")
    _, prepare = wiring.education_from_env(lessons=seed_catalog())
    assert prepare is not None


class _CountingLessons:
    def __init__(self) -> None:
        self.catalog = seed_catalog()
        self.calls = 0

    async def list_demos(self, language=None):
        self.calls += 1
        return await self.catalog.list_demos(language)

    async def list_glossary(self, language=None):
        self.calls += 1
        return await self.catalog.list_glossary(language)

    async def lessons_version(self):
        return self.catalog.generation


async def test_lessons_are_cached_until_catalog_reload() -> None:
    lessons = _CountingLessons()
    service = build_education_service(lessons=lessons)
    first = await service.list_demos("en")
    assert await service.list_demos("en") == first
    assert await service.list_glossary("uk") == await service.list_glossary("uk")
    assert lessons.calls == 2
    await lessons.catalog.reload(role="admin")
    await service.list_demos("en")
    assert lessons.calls == 3
    quizzes = await service.list_quizzes("uk")
    assert await service.list_quizzes("uk") == quizzes


async def test_badge_cache_is_invalidated_on_award() -> None:
    service = build_education_service(lessons=seed_catalog())
    assert await service.list_badges(user_id="s1") == []
    await service.award("s1", "demo", "demo_arctic")
    assert [item.code for item in await service.list_badges(user_id="s1")] == ["demo"]
    assert [item.code for item in await service.list_badges(user_id="s1")] == ["demo"]


async def test_share_lookup_survives_a_stale_cache_entry() -> None:
    service = build_education_service(lessons=seed_catalog())
    created = await service.create_assignment(teacher_id="t1", role="teacher", title="T", student_ids=[], case_ids=[])
    old = await service.share(created.id, actor_id="t1", role="teacher")
    assert (await service.open_shared(old.token)).id == created.id
    assert (await service.open_shared(old.token)).id == created.id
    new = await service.share(created.id, actor_id="t1", role="teacher")
    assert new.token != old.token
    assert (await service.open_shared(new.token)).id == created.id
    with pytest.raises(Exception):
        await service.open_shared(old.token)
