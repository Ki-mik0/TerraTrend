"""Warm-up jobs for `POST /admin/warm-cache`. Each returns how many entries it filled."""

from __future__ import annotations

from earthtrend.api.application.cache.service import FamilyStats, Warmer
from earthtrend.api.application.education.service import EducationService
from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.application.tiles.service import TileService
from earthtrend.api.domain.radar.model import FEEDS
from earthtrend.api.domain.tiles.model import TileRequest
from earthtrend.api.infrastructure.shared.metrics import CACHE_ERRORS, CACHE_HITS, CACHE_MISSES

LANGUAGES = ("uk", "en")
WARM_MAX_ZOOM = 2


def radar_warmer(radar: RadarService) -> Warmer:
    async def warm() -> int:
        for feed in sorted(FEEDS):
            await radar.page(feed=feed)
        await radar.typology()
        return len(FEEDS) + 1

    return warm


def education_warmer(education: EducationService) -> Warmer:
    async def warm() -> int:
        for language in LANGUAGES:
            await education.list_demos(language)
            await education.list_glossary(language)
            await education.list_quizzes(language)
        return 3 * len(LANGUAGES)

    return warm


def tiles_warmer(tiles: TileService, *, max_zoom: int = WARM_MAX_ZOOM) -> Warmer:
    async def warm() -> int:
        count = 0
        for product in await tiles.products():
            for z in range(max_zoom + 1):
                for x in range(2**z):
                    for y in range(2**z):
                        await tiles.tile(
                            TileRequest(
                                product="trend",
                                z=z,
                                x=x,
                                y=y,
                                variable_id=product.variable_id,
                                period=product.period,
                                season=product.season,
                            )
                        )
                        count += 1
        return count

    return warm


def prometheus_stats() -> dict[str, FamilyStats]:
    """Hits, misses and errors per family, read back from the Prometheus counters."""
    families: dict[str, dict[str, float]] = {}
    for name, counter in (("hits", CACHE_HITS), ("misses", CACHE_MISSES), ("errors", CACHE_ERRORS)):
        for metric in counter.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    families.setdefault(sample.labels["family"], {})[name] = sample.value
    return {
        family: FamilyStats(hits=values.get("hits", 0.0), misses=values.get("misses", 0.0), errors=values.get("errors", 0.0))
        for family, values in sorted(families.items())
    }
