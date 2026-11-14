"""Grid products from the analytics package (`GridTrendProduct`), stored as numpy files.

Layout under the grid root (default `STORAGE_ROOT/grids`):

    index.json   {"products": [{"variable_id", "period", "season", "version", "file",
                                 "bbox": [west, south, east, north], "resolution", "vmax", "years": [...]}]}
    <file>.npz   slope, sig_fdr, ai_class, ai_step_prob, and optional anomaly_<year> frames

Rows run north to south, columns west to east. Without `index.json` a deterministic synthetic
seed is served, so the map works before the first analytics run.
"""

from __future__ import annotations

import asyncio
import json
import zlib
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from earthtrend.api.application.tiles.ports import GridArrays
from earthtrend.api.domain.tiles.model import GridProduct, TileError, parse_period

_log = structlog.get_logger("tiles.grids")
SEED_VERSION = "seed-grid-1"
SEED_PERIOD = "2000-2024"
_SEED_VARIABLES = ("gldas_sm", "merra2_t2m", "modis_ndvi")
_SEED_SEASONS = ("annual", "JJA")
LRU_SIZE = 8


def _seed_fields(variable_id: str, season: str) -> dict[str, np.ndarray]:
    """Smooth synthetic slopes with a plausible geography, deterministic per variable and season."""
    lat = np.linspace(89.5, -89.5, 180)[:, None]
    lon = np.linspace(-179.5, 179.5, 360)[None, :]
    rng = np.random.default_rng(zlib.crc32(f"{variable_id}:{season}".encode()))
    if variable_id == "merra2_t2m":
        slope = 0.15 + 0.6 * (np.abs(lat) / 90) ** 2 * (1.3 if season == "annual" else 0.8)
    elif variable_id == "gldas_sm":
        slope = -0.03 * np.exp(-(((lat - 40) / 15) ** 2)) + 0.015 * np.exp(-(((lat + 5) / 10) ** 2))
    else:
        slope = 0.02 * np.exp(-(((lat - 60) / 12) ** 2)) - 0.01 * np.exp(-(((lat - 15) / 8) ** 2))
    slope = slope * (1 + 0.3 * np.sin(np.radians(lon) * 3)) + rng.normal(0, 0.05, (180, 360)) * np.abs(slope).max()
    vmax = float(np.percentile(np.abs(slope), 98))
    sig = (np.abs(slope) > 0.35 * vmax).astype(np.uint8)
    ai_class = np.where(sig == 0, 0, np.where(np.abs(lat) > 60, 3, 1)).astype(np.uint8)
    ai_class = np.where((sig == 1) & (rng.random((180, 360)) < 0.05), 2, ai_class).astype(np.uint8)
    return {"slope": slope.astype(np.float32), "sig_fdr": sig, "ai_class": ai_class, "vmax": np.float32(vmax)}


def seed_products() -> list[GridProduct]:
    start, end = parse_period(SEED_PERIOD)
    products = []
    for variable_id in _SEED_VARIABLES:
        for season in _SEED_SEASONS:
            vmax = float(_seed_fields(variable_id, season)["vmax"])
            products.append(
                GridProduct(
                    variable_id=variable_id,
                    period=SEED_PERIOD,
                    season=season,
                    version=SEED_VERSION,
                    bbox=(-180.0, -90.0, 180.0, 90.0),
                    resolution=1.0,
                    vmax=vmax,
                    years=tuple(range(start, end + 1)),
                    file=f"seed:{variable_id}:{season}",
                )
            )
    return products


class FileGridStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._seed = seed_products()
        self._arrays: OrderedDict[tuple[str, str, int | None], GridArrays] = OrderedDict()
        self._index: tuple[float, list[GridProduct]] | None = None
        self.loads = 0

    async def version(self) -> str:
        products = await self._all()
        return ",".join(sorted({item.version for item in products})) or "none"

    async def _all(self) -> list[GridProduct]:
        index = self.root / "index.json"
        if not index.exists():
            return self._seed
        mtime = index.stat().st_mtime
        if self._index is not None and self._index[0] == mtime:
            return self._index[1]
        raw = await asyncio.to_thread(lambda: json.loads(index.read_text(encoding="utf-8")))
        products: list[GridProduct] = []
        for row in raw.get("products", []):
            try:
                products.append(
                    GridProduct(
                        variable_id=row["variable_id"],
                        period=row["period"],
                        season=row.get("season", "annual"),
                        version=str(row["version"]),
                        bbox=tuple(float(value) for value in row["bbox"]),  # type: ignore[arg-type]
                        resolution=float(row["resolution"]),
                        vmax=float(row["vmax"]),
                        years=tuple(int(year) for year in row.get("years", ())),
                        file=str(row["file"]),
                    )
                )
            except (KeyError, TypeError, ValueError, TileError) as error:
                _log.warning("grid_product_skipped", row=row.get("file"), reason=str(error))
        self._index = (mtime, products)
        return products

    async def find(self, variable_id: str, period: str, season: str) -> GridProduct | None:
        for product in await self._all():
            if (product.variable_id, product.period, product.season) == (variable_id, period, season):
                return product
        return None

    async def products(self, variable_id: str | None = None) -> list[GridProduct]:
        return [item for item in await self._all() if variable_id is None or item.variable_id == variable_id]

    async def arrays(self, product: GridProduct, year: int | None) -> GridArrays:
        key = (product.version, product.file, year)
        cached = self._arrays.get(key)
        if cached is not None:
            self._arrays.move_to_end(key)
            return cached
        self.loads += 1
        fields = await asyncio.to_thread(self._read, product)
        values = fields["slope"]
        if year is not None:
            frame = fields.get(f"anomaly_{year}")
            if frame is None:
                start, end = parse_period(product.period)
                frame = values * (year - (start + end) / 2) / 10.0
            values = frame
        arrays = GridArrays(values=values, sig_fdr=fields["sig_fdr"], ai_class=fields["ai_class"])
        self._arrays[key] = arrays
        if len(self._arrays) > LRU_SIZE:
            self._arrays.popitem(last=False)
        return arrays

    def _read(self, product: GridProduct) -> dict[str, Any]:
        if product.file.startswith("seed:"):
            _, variable_id, season = product.file.split(":")
            return _seed_fields(variable_id, season)
        path = (self.root / product.file).resolve()
        if self.root.resolve() not in path.parents:
            raise TileError("grid_invalid", "Файл сітки поза каталогом сіток")
        with np.load(path.with_suffix(".npz"), allow_pickle=False) as data:
            return {name: data[name] for name in data.files}

    async def save_analyzed(self, *, variable_id: str, period: str, season: str, product) -> GridProduct:
        file_name = f"{variable_id}-{period}-{season}"
        slope = np.asarray(product.fields.slope)
        sig = np.asarray(product.sig_fdr)
        ai = product.ai_class if product.ai_class is not None else np.zeros(slope.shape, dtype=np.int64)
        step = product.ai_step_prob if product.ai_step_prob is not None else np.zeros(slope.shape)
        path = self.root / f"{file_name}.npz"

        def _write() -> None:
            self.root.mkdir(parents=True, exist_ok=True)
            np.savez(path, slope=slope, sig_fdr=sig, ai_class=ai, ai_step_prob=step)
            index_path = self.root / "index.json"
            current = {"products": []}
            if index_path.exists():
                current = json.loads(index_path.read_text(encoding="utf-8"))
            row = {
                "variable_id": variable_id,
                "period": period,
                "season": season,
                "version": product.summary.analytics_version,
                "file": file_name,
                "bbox": [float(np.min(product.lon)), float(np.min(product.lat)), float(np.max(product.lon)), float(np.max(product.lat))],
                "resolution": float(abs(product.lat[1] - product.lat[0])) if len(product.lat) > 1 else 1.0,
                "vmax": float(np.nanmax(np.abs(slope))) if slope.size else 1.0,
                "years": [],
            }
            current["products"] = [item for item in current.get("products", []) if item.get("file") != file_name]
            current["products"].append(row)
            index_path.write_text(json.dumps(current), encoding="utf-8")

        await asyncio.to_thread(_write)
        self._index = None
        return GridProduct(
            variable_id=variable_id,
            period=period,
            season=season,
            version=product.summary.analytics_version,
            bbox=(float(np.min(product.lon)), float(np.min(product.lat)), float(np.max(product.lon)), float(np.max(product.lat))),
            resolution=float(abs(product.lat[1] - product.lat[0])) if len(product.lat) > 1 else 1.0,
            vmax=float(np.nanmax(np.abs(slope))) if slope.size else 1.0,
            years=(),
            file=file_name,
        )
