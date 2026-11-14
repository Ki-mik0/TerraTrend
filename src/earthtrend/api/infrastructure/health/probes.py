"""Health probes for the database, the cache, storage, analytics products and models.

Details never contain a URL or a password: only the dialect, a host-free name or a version.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.application.health.ports import ProbeResult


class DatabaseProbe:
    name = "database"
    critical = True

    def __init__(self, url: str, engine: AsyncEngine | None = None) -> None:
        self._url = url
        self._engine = engine

    async def check(self) -> ProbeResult:
        if not self._url:
            return ProbeResult(status="skipped", detail="memory stores, DB_URL not set")
        dialect = make_url(self._url).get_backend_name()
        if self._engine is None:
            self._engine = create_async_engine(self._url, poolclass=NullPool)
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return ProbeResult(status="ok", info={"dialect": dialect})


class CacheProbe:
    name = "cache"
    critical = False

    def __init__(self, ping: Callable[[], Awaitable[bool]], *, backend: str) -> None:
        self._ping = ping
        self._backend = backend

    async def check(self) -> ProbeResult:
        if self._backend == "memory":
            return ProbeResult(status="skipped", detail="in-process cache, REDIS_URL not set")
        alive = await self._ping()
        return ProbeResult(status="ok" if alive else "down", info={"backend": self._backend})


class StorageProbe:
    name = "storage"
    critical = True

    def __init__(self, ping: Callable[[], Awaitable[bool]]) -> None:
        self._ping = ping

    async def check(self) -> ProbeResult:
        if await self._ping():
            return ProbeResult(status="ok")
        return ProbeResult(status="down", detail="storage is not writable")


class AnalyticsProbe:
    """Analytics products the API serves without recomputing: the radar scan and the grids."""

    name = "analytics"
    critical = False

    def __init__(self, versions: dict[str, Callable[[], Awaitable[str]]]) -> None:
        self._versions = versions

    async def check(self) -> ProbeResult:
        info = {}
        for name, version in self._versions.items():
            info[name] = await version()
        seeded = [name for name, value in info.items() if value.startswith("seed")]
        if seeded:
            return ProbeResult(status="degraded", detail="built-in seed: " + ", ".join(seeded), info=info)
        return ProbeResult(status="ok", info=info)


class ModelsProbe:
    name = "models"
    critical = False

    def __init__(self, root: Path) -> None:
        self._root = root

    async def check(self) -> ProbeResult:
        if not await asyncio.to_thread(self._root.is_dir):
            return ProbeResult(status="degraded", detail="models directory is missing")
        names = sorted(item.name for item in await asyncio.to_thread(lambda: list(self._root.iterdir())))
        found = {name: "present" for name in names if name.lower().startswith(("m1", "m2", "m3", "m4"))}
        return ProbeResult(status="ok", info=found)


def models_root() -> Path:
    return Path(os.environ.get("MODELS_DIR", "models"))
