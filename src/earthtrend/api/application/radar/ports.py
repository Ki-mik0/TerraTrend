"""Port to the precomputed radar product written by analytics."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.radar.model import RadarProduct


class RadarProductPort(Protocol):
    async def latest_version(self) -> str:
        """Cheap: the version of the newest product. A new monthly scan changes it."""
        ...

    async def load(self, version: str) -> RadarProduct: ...
