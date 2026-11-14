"""Cache admin: stats, clear a key family, warm the hot reads. Admin only, every action audited."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from earthtrend.api.application.shared.cache import AdminCachePort

FAMILIES = ("edu", "radar", "story", "case", "catalog", "assistant", "tile")
TILE_FAMILY = "tile"

Warmer = Callable[[], Awaitable[int]]


class CacheError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class AuditPort(Protocol):
    async def record_admin(self, *, actor_id: str, role: str, action: str, subject_id: str) -> object: ...


class BytesStore(Protocol):
    async def delete_prefix(self, prefix: str) -> int: ...


@dataclass(frozen=True)
class FamilyStats:
    hits: float
    misses: float
    errors: float

    @property
    def hit_ratio(self) -> float | None:
        total = self.hits + self.misses
        return None if total == 0 else round(self.hits / total, 4)


@dataclass(frozen=True)
class WarmReport:
    warmed: dict[str, int]
    failed: dict[str, str]
    took_ms: float


class CacheAdmin:
    def __init__(
        self,
        *,
        cache: AdminCachePort,
        storage: BytesStore,
        audit: AuditPort,
        warmers: dict[str, Warmer],
        stats: Callable[[], dict[str, FamilyStats]],
        backend: str,
    ) -> None:
        self._cache = cache
        self._storage = storage
        self._audit = audit
        self._warmers = warmers
        self._stats = stats
        self.backend = backend

    async def stats(self, *, actor_id: str, role: str) -> tuple[str, bool, dict[str, FamilyStats]]:
        self._require_admin(role)
        del actor_id
        return self.backend, await self._cache.ping(), self._stats()

    async def clear(self, family: str, *, actor_id: str, role: str) -> int:
        self._require_admin(role)
        if family != "all" and family not in FAMILIES:
            raise CacheError("family_unknown", "Невідома родина кешу")
        targets = FAMILIES if family == "all" else (family,)
        removed = 0
        for name in targets:
            if name == TILE_FAMILY:
                removed += await self._storage.delete_prefix(f"{TILE_FAMILY}/")
            removed += await self._cache.delete_prefix(f"{name}:")
        await self._audit.record_admin(actor_id=actor_id, role=role, action="clear_cache", subject_id=family)
        return removed

    async def warm(self, *, actor_id: str, role: str) -> WarmReport:
        """Fill the hot reads: radar pages, lessons, low-zoom tiles. One failing warmer does not stop the rest."""
        self._require_admin(role)
        started = time.perf_counter()
        warmed: dict[str, int] = {}
        failed: dict[str, str] = {}
        for name, warmer in self._warmers.items():
            try:
                warmed[name] = await warmer()
            except Exception as error:
                failed[name] = type(error).__name__
        await self._audit.record_admin(actor_id=actor_id, role=role, action="warm_cache", subject_id="all")
        return WarmReport(warmed=warmed, failed=failed, took_ms=round((time.perf_counter() - started) * 1000, 1))

    @staticmethod
    def _require_admin(role: str) -> None:
        if role != "admin":
            raise CacheError("forbidden", "Кеш прогріває і чистить лише admin")
