"""Page the precomputed radar feed and its typology. The backend does not recompute slopes.

Every cache key carries the product version, so a new monthly scan makes old pages unreachable.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from earthtrend.api.application.radar.ports import RadarProductPort
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.domain.radar.model import (
    RadarItem,
    RadarPage,
    TypologyCluster,
    require_feed,
    require_page,
    require_season,
)

VERSION_TTL = 60
PAGE_TTL = 3600


def _page_from(raw: dict[str, Any]) -> RadarPage:
    raw["items"] = [RadarItem(**item) for item in raw["items"]]
    return RadarPage(**raw)


def _cluster_from(raw: dict[str, Any]) -> TypologyCluster:
    raw["region_ids"] = tuple(raw["region_ids"])
    return TypologyCluster(**raw)


class RadarService:
    def __init__(self, *, product: RadarProductPort, cache: CachePort) -> None:
        self._product = product
        self._cache = cache
        self._overlay = None

    async def version(self) -> str:
        if self._overlay is not None:
            return self._overlay.version
        cached = await self._cache.get_json("radar:version")
        if cached is not None:
            return cached
        version = await self._product.latest_version()
        await self._cache.set_json("radar:version", version, VERSION_TTL)
        return version

    async def page(
        self,
        *,
        feed: str,
        variable_id: str | None = None,
        region_id: str | None = None,
        season: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RadarPage:
        require_feed(feed)
        require_season(season)
        require_page(page, page_size)
        version = await self.version()
        if self._overlay is not None:
            return self._overlay.page(
                feed=feed,
                variable_id=variable_id,
                region_id=region_id,
                season=season,
                page=page,
                page_size=page_size,
            )
        key = f"radar:feed:{version}:{feed}:{variable_id or '*'}:{region_id or '*'}:{season or '*'}:{page}:{page_size}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return _page_from(cached)
        product = await self._product.load(version)
        result = product.page(
            feed=feed, variable_id=variable_id, region_id=region_id, season=season, page=page, page_size=page_size
        )
        await self._cache.set_json(key, asdict(result), PAGE_TTL)
        return result

    async def scan(self, rows: list[dict]):
        from earthtrend.api.infrastructure.analytics_bridge import run_blocking, scan_radar
        from earthtrend.api.domain.radar.model import RadarItem, RadarProduct, TypologyCluster

        run = await run_blocking(scan_radar, rows)
        items: list[RadarItem] = []
        by_key = {entry.key: entry for entry in run.entries}
        for feed in (
            "strongest",
            "opposite",
            "accelerating",
            "breakpoints",
            "almost",
            "stable",
            "ai_flagged",
        ):
            for key in getattr(run.feeds, feed):
                entry = by_key.get(key)
                if entry is None:
                    continue
                candidate = entry.candidate
                try:
                    items.append(
                        RadarItem(
                            id=key,
                            feed=feed,
                            variable_id=candidate.variable_id,
                            region_id=candidate.region_id,
                            direction=entry.direction,
                            slope_decade=float(candidate.slope_per_decade or 0.0),
                            pct_decade=0.0,
                            snr=float(candidate.snr or 0.0),
                            p_mk=float(candidate.p_mk or 1.0),
                            p_ols=float(candidate.p_mk or 1.0),
                            q_fdr=float(candidate.q_global or 1.0),
                            split_flag=entry.split_flag,
                            score=float(entry.radar_score),
                            verdict_level=entry.verdict,
                            case_id=key,
                            season=candidate.season,
                            novelty=entry.novelty,
                            years_to_detect=entry.years_to_detect_remaining,
                            area_km2=float(candidate.region_area_km2 or 0.0),
                        )
                    )
                except Exception:
                    continue
        clusters = ()
        if run.typology is not None:
            clusters = tuple(
                TypologyCluster(
                    id=str(cluster.id),
                    pattern=cluster.code,
                    signs=cluster.signs,
                    season=run.typology.season or "annual",
                    region_ids=tuple(
                        region for region, assigned in run.typology.assignments.items() if assigned == cluster.id
                    ),
                )
                for cluster in run.typology.clusters
                if cluster.signs
            )
        self._overlay = RadarProduct(
            version=f"scan-{run.analytics_version}-{run.n_series}",
            generated_at="analytics",
            items=tuple(items),
            clusters=clusters,
        )
        return {"version": self._overlay.version, "entries": len(run.entries), "cards": len(items)}

    async def typology(
        self, *, variables: list[str] | None = None, season: str | None = None
    ) -> tuple[str, list[TypologyCluster]]:
        require_season(season)
        wanted = sorted(set(variables or []))
        version = await self.version()
        if self._overlay is not None:
            clusters = self._overlay.typology(variables=wanted or None, season=season)
            return version, clusters
        key = f"radar:typology:{version}:{season or '*'}:{','.join(wanted) or '*'}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return version, [_cluster_from(item) for item in cached]
        product = await self._product.load(version)
        clusters = product.typology(variables=wanted or None, season=season)
        await self._cache.set_json(key, [asdict(item) for item in clusters], PAGE_TTL)
        return version, clusters

    async def feed(
        self,
        *,
        feed: str,
        variable_id: str | None = None,
        region_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[RadarItem]:
        """The cards alone. Kept for the assistant's `get_radar` tool."""
        result = await self.page(
            feed=feed, variable_id=variable_id, region_id=region_id, page=page, page_size=page_size
        )
        return result.items
