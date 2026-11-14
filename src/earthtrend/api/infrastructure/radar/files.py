"""Radar product files written by the analytics scan.

Layout under the radar root (default `STORAGE_ROOT/radar`):

    latest.json          {"version": "2026-11"}
    2026-11.json         {"version", "generated_at", "items": [...], "clusters": [...]}

A new monthly scan writes a new version file, then swaps `latest.json`. The backend picks it up
without a restart. A row that breaks a domain rule is skipped and logged; the rest still loads.
Without `latest.json` the built-in seed is served.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import structlog

from earthtrend.api.domain.radar.model import RadarError, RadarItem, RadarProduct, TypologyCluster
from earthtrend.api.infrastructure.radar.seed import seed_product

_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_log = structlog.get_logger("radar.files")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse(raw: dict[str, Any]) -> RadarProduct:
    items: list[RadarItem] = []
    for row in raw.get("items", []):
        try:
            items.append(RadarItem(**row))
        except (RadarError, TypeError) as error:
            _log.warning("radar_row_skipped", row_id=row.get("id"), reason=str(error))
    clusters: list[TypologyCluster] = []
    for row in raw.get("clusters", []):
        try:
            clusters.append(TypologyCluster(**{**row, "region_ids": tuple(row.get("region_ids", ()))}))
        except (RadarError, TypeError) as error:
            _log.warning("radar_cluster_skipped", cluster_id=row.get("id"), reason=str(error))
    return RadarProduct(
        version=str(raw["version"]),
        generated_at=str(raw.get("generated_at", "")),
        items=tuple(items),
        clusters=tuple(clusters),
    )


class FileRadarProduct:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._seed = seed_product()
        self._loaded: RadarProduct | None = None

    async def latest_version(self) -> str:
        pointer = self.root / "latest.json"
        if not pointer.exists():
            return self._seed.version
        version = str((await asyncio.to_thread(_read_json, pointer))["version"])
        if not _VERSION.match(version):
            raise RadarError("product_invalid", "Некоректна версія продукту радару")
        return version

    async def load(self, version: str) -> RadarProduct:
        if version == self._seed.version:
            return self._seed
        if self._loaded is not None and self._loaded.version == version:
            return self._loaded
        if not _VERSION.match(version):
            raise RadarError("product_invalid", "Некоректна версія продукту радару")
        raw = await asyncio.to_thread(_read_json, self.root / f"{version}.json")
        self._loaded = _parse(raw)
        return self._loaded
