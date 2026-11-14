"""Wire map tiles: grid files under `STORAGE_ROOT/grids`, PNGs stored under `STORAGE_ROOT`."""

from __future__ import annotations

import os
from pathlib import Path

from earthtrend.api.application.tiles.ports import ObjectStorage, VariableCheck
from earthtrend.api.application.tiles.service import TileService
from earthtrend.api.infrastructure.shared.metrics import TILE_RENDER_SECONDS, TILE_REQUESTS
from earthtrend.api.infrastructure.shared.storage import LocalObjectStorage
from earthtrend.api.infrastructure.tiles.grids import FileGridStore
from earthtrend.api.infrastructure.tiles.png_tile_renderer import PillowTileRenderer


class PrometheusTileMetrics:
    def observe(self, product: str, outcome: str, seconds: float | None) -> None:
        TILE_REQUESTS.labels(product=product, outcome=outcome).inc()
        if seconds is not None:
            TILE_RENDER_SECONDS.labels(product=product).observe(seconds)


def storage_root() -> Path:
    return Path(os.environ.get("STORAGE_ROOT", "data/storage"))


def build_tile_service(
    *, catalog: VariableCheck, storage: ObjectStorage, grids: FileGridStore | None = None
) -> TileService:
    return TileService(
        grids=grids or FileGridStore(storage_root() / "grids"),
        renderer=PillowTileRenderer(),
        storage=storage,
        catalog=catalog,
        metrics=PrometheusTileMetrics(),
    )


def tiles_from_env(catalog: VariableCheck, storage: ObjectStorage | None = None) -> TileService:
    return build_tile_service(catalog=catalog, storage=storage or LocalObjectStorage(storage_root()))
