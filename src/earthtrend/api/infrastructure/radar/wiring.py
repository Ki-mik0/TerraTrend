"""Wire the radar: product files under `STORAGE_ROOT/radar`, cache from `REDIS_URL`."""

from __future__ import annotations

import os
from pathlib import Path

from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.infrastructure.radar.files import FileRadarProduct
from earthtrend.api.infrastructure.shared.cache import cache_from_env


def radar_from_env(cache: CachePort | None = None) -> RadarService:
    root = Path(os.environ.get("STORAGE_ROOT", "data/storage")) / "radar"
    return RadarService(product=FileRadarProduct(root), cache=cache if cache is not None else cache_from_env())
