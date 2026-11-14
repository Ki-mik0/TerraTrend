"""Radar product held in memory: the built-in seed for tests and local runs."""

from __future__ import annotations

from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.domain.radar.model import RadarProduct
from earthtrend.api.infrastructure.radar.seed import seed_product
from earthtrend.api.infrastructure.shared.cache import MemoryCache


class MemoryRadarProduct:
    def __init__(self, product: RadarProduct | None = None) -> None:
        self.product = product or seed_product()
        self.loads = 0

    async def latest_version(self) -> str:
        return self.product.version

    async def load(self, version: str) -> RadarProduct:
        del version
        self.loads += 1
        return self.product


def seed_radar() -> RadarService:
    return RadarService(product=MemoryRadarProduct(), cache=MemoryCache())
