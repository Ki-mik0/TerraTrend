import asyncio
from pathlib import Path

from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.api.health.routes import health_router
from earthtrend.api.application.health.ports import ProbeResult
from earthtrend.api.application.health.service import HealthCheck
from earthtrend.api.infrastructure.health.probes import (
    AnalyticsProbe,
    CacheProbe,
    DatabaseProbe,
    ModelsProbe,
    StorageProbe,
)
from earthtrend.api.infrastructure.health.wiring import app_version, health_from_env
from earthtrend.api.main import create_app


class _Probe:
    def __init__(self, name: str, status: str, *, critical: bool, delay: float = 0.0, boom: bool = False) -> None:
        self.name = name
        self.critical = critical
        self._status = status
        self._delay = delay
        self._boom = boom

    async def check(self) -> ProbeResult:
        await asyncio.sleep(self._delay)
        if self._boom:
            raise RuntimeError("secret://user:pass@host")
        return ProbeResult(status=self._status)


def _client(*probes) -> TestClient:
    health = HealthCheck(probes=list(probes), version="9.9.9", timeout=0.05)
    return TestClient(Litestar(route_handlers=[health_router(health)]))


def test_app_health_routes_in_memory_configuration() -> None:
    with TestClient(create_app()) as client:
        live = client.get("/health/live")
        assert live.status_code == 200 and live.json()["checks"] == {}
        assert live.headers["cache-control"] == "no-store"
        ready = client.get("/health/ready").json()
        assert ready["status"] == "ok" and set(ready["checks"]) == {"database", "storage"}
        assert ready["checks"]["database"]["status"] == "skipped"
        full = client.get("/health").json()
        assert set(full["checks"]) == {"database", "storage", "cache", "analytics", "models"}
        assert full["checks"]["analytics"]["info"]["radar"] == "seed-1"
        assert full["status"] in {"ok", "degraded"} and full["version"] == app_version()


def test_critical_failure_is_503_and_optional_failure_degrades() -> None:
    with _client(_Probe("database", "down", critical=True), _Probe("cache", "ok", critical=False)) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health").json()["status"] == "down"
        assert client.get("/health/live").status_code == 200
    with _client(_Probe("database", "ok", critical=True), _Probe("cache", "down", critical=False)) as client:
        body = client.get("/health").json()
        assert body["status"] == "degraded" and body["checks"]["cache"]["status"] == "degraded"
        assert client.get("/health/ready").status_code == 200


def test_timeout_and_exception_are_down_without_leaking_details() -> None:
    with _client(_Probe("slow", "ok", critical=True, delay=1), _Probe("boom", "ok", critical=True, boom=True)) as client:
        body = client.get("/health").json()
        assert body["checks"]["slow"]["status"] == "down" and "timeout" in body["checks"]["slow"]["detail"]
        assert body["checks"]["boom"]["detail"] == "RuntimeError"
        assert "pass" not in client.get("/health").text


async def test_probes(tmp_path: Path) -> None:
    assert (await DatabaseProbe("").check()).status == "skipped"
    url = f"sqlite+aiosqlite:///{tmp_path / 'h.db'}"
    database = await DatabaseProbe(url).check()
    assert database.status == "ok" and database.info == {"dialect": "sqlite"}
    engine = create_async_engine(url)
    assert (await DatabaseProbe(url, engine).check()).status == "ok"
    await engine.dispose()

    async def yes() -> bool:
        return True

    async def no() -> bool:
        return False

    assert (await CacheProbe(yes, backend="memory").check()).status == "skipped"
    assert (await CacheProbe(no, backend="redis").check()).status == "down"
    assert (await StorageProbe(yes).check()).status == "ok"
    assert (await StorageProbe(no).check()).status == "down"

    async def real() -> str:
        return "2026-11"

    async def seed() -> str:
        return "seed-1"

    assert (await AnalyticsProbe({"radar": real}).check()).status == "ok"
    seeded = await AnalyticsProbe({"radar": real, "grids": seed}).check()
    assert seeded.status == "degraded" and "grids" in seeded.detail

    assert (await ModelsProbe(tmp_path / "missing").check()).status == "degraded"
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m1_trendnet_v3").mkdir()
    models = await ModelsProbe(tmp_path / "models").check()
    assert models.status == "ok" and models.info == {"m1_trendnet_v3": "present"}


def test_health_from_env_hides_non_postgres_urls(monkeypatch) -> None:
    async def yes() -> bool:
        return True

    monkeypatch.setenv("DB_URL", "sqlite+aiosqlite:///x.db")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    health = health_from_env(cache_ping=yes, storage_ping=yes, product_versions={})
    database, _, cache, *_ = health._probes
    assert database._url == "" and cache._backend == "redis"
