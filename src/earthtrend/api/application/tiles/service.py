"""GetTile: a PNG of a precomputed grid product, rendered once and then served from storage.

The data version is part of the storage key, so a new grid product never serves an old tile.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol

from earthtrend.api.application.tiles.ports import GridPort, ObjectStorage, TileRenderer, VariableCheck
from earthtrend.api.domain.tiles.model import GridProduct, TileError, TileRequest


# Bump when the renderer draws differently, so PNGs stored by the old renderer are not served.
RENDER_VERSION = "r2"


class TileMetrics(Protocol):
    def observe(self, product: str, outcome: str, seconds: float | None) -> None: ...


class NullTileMetrics:
    def observe(self, product: str, outcome: str, seconds: float | None) -> None:
        del product, outcome, seconds


@dataclass(frozen=True)
class TileResult:
    data: bytes
    etag: str
    outcome: str  # hit, miss or empty


class TileService:
    def __init__(
        self,
        *,
        grids: GridPort,
        renderer: TileRenderer,
        storage: ObjectStorage,
        catalog: VariableCheck,
        metrics: TileMetrics | None = None,
    ) -> None:
        self._grids = grids
        self._renderer = renderer
        self._storage = storage
        self._catalog = catalog
        self._metrics = metrics or NullTileMetrics()
        self._empty: bytes | None = None

    async def product_for(self, request: TileRequest) -> GridProduct:
        try:
            await self._catalog.get_variable(request.variable_id)
        except Exception as error:
            if getattr(error, "code", "") == "variable_not_found":
                raise TileError("variable_not_found", "Змінну не знайдено") from error
            raise
        product = await self._grids.find(request.variable_id, request.period, request.season)
        if product is None:
            raise TileError("grid_not_found", "Для цієї змінної, періоду і сезону немає сітки")
        if not product.has_frame(request.year):
            raise TileError("grid_not_found", "Для цього року немає кадру")
        return product

    async def tile(self, request: TileRequest) -> TileResult:
        product = await self.product_for(request)
        key = request.storage_key(f"{product.version}.{RENDER_VERSION}")
        etag = '"' + hashlib.sha256(key.encode()).hexdigest()[:20] + '"'
        if not product.overlaps(request.bounds()):
            self._metrics.observe(request.product, "empty", None)
            return TileResult(data=self.empty(), etag=etag, outcome="empty")
        stored = await self._storage.get(key)
        if stored is not None:
            self._metrics.observe(request.product, "hit", None)
            return TileResult(data=stored, etag=etag, outcome="hit")
        started = time.perf_counter()
        arrays = await self._grids.arrays(product, request.year)
        data = self._renderer.render(request, product, arrays)
        await self._storage.put(key, data)
        self._metrics.observe(request.product, "miss", time.perf_counter() - started)
        return TileResult(data=data, etag=etag, outcome="miss")

    async def etag_for(self, request: TileRequest) -> str:
        """The ETag without reading or rendering the tile, for a cheap 304."""
        product = await self.product_for(request)
        return '"' + hashlib.sha256(request.storage_key(f"{product.version}.{RENDER_VERSION}").encode()).hexdigest()[:20] + '"'

    async def grid_version(self) -> str:
        return await self._grids.version()

    async def products(self, variable_id: str | None = None) -> list[GridProduct]:
        return await self._grids.products(variable_id)

    def empty(self) -> bytes:
        if self._empty is None:
            self._empty = self._renderer.empty()
        return self._empty
