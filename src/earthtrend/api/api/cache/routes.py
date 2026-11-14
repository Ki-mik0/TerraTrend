"""Cache admin routes: stats, warm-up, clear by family. Admin only."""

from __future__ import annotations

from litestar import Request, Router, delete, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromQuery
from pydantic import BaseModel

from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.cache.service import CacheAdmin, CacheError
from earthtrend.api.application.identity.service import IdentityService


class FamilyStatsResponse(BaseModel):
    hits: float
    misses: float
    errors: float
    hit_ratio: float | None


class CacheStatsResponse(BaseModel):
    backend: str
    reachable: bool
    families: dict[str, FamilyStatsResponse]


class WarmResponse(BaseModel):
    warmed: dict[str, int]
    failed: dict[str, str]
    took_ms: float


class ClearResponse(BaseModel):
    family: str
    removed: int


def _http(error: CacheError) -> HTTPException:
    status = 403 if error.code == "forbidden" else 422
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def cache_router(admin: CacheAdmin, identity: IdentityService) -> Router:
    @get("/admin/cache")
    async def cache_stats(request: Request) -> CacheStatsResponse:
        actor = await require_actor(request, identity)
        try:
            backend, reachable, families = await admin.stats(actor_id=actor.id, role=actor.role)
        except CacheError as error:
            raise _http(error) from error
        return CacheStatsResponse(
            backend=backend,
            reachable=reachable,
            families={
                name: FamilyStatsResponse(hits=item.hits, misses=item.misses, errors=item.errors, hit_ratio=item.hit_ratio)
                for name, item in families.items()
            },
        )

    @post("/admin/warm-cache", status_code=200)
    async def warm_cache(request: Request) -> WarmResponse:
        actor = await require_actor(request, identity)
        try:
            report = await admin.warm(actor_id=actor.id, role=actor.role)
        except CacheError as error:
            raise _http(error) from error
        return WarmResponse(warmed=report.warmed, failed=report.failed, took_ms=report.took_ms)

    @delete("/admin/cache", status_code=200)
    async def clear_cache(request: Request, family: FromQuery[str]) -> ClearResponse:
        actor = await require_actor(request, identity)
        try:
            removed = await admin.clear(family, actor_id=actor.id, role=actor.role)
        except CacheError as error:
            raise _http(error) from error
        return ClearResponse(family=family, removed=removed)

    return Router(path="/api/v1", route_handlers=[cache_stats, warm_cache, clear_cache])
