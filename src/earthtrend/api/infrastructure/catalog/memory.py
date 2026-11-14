"""In-memory catalog and optional M3 search."""

from __future__ import annotations

from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.domain.catalog.model import TrendPotential
from earthtrend.api.infrastructure.catalog.curated import (
    curated_events,
    curated_links,
    curated_passports,
    curated_regions,
)
from earthtrend.api.infrastructure.catalog.lessons import seed_demos, seed_glossary


class MemorySearch:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.synonyms = {"посуха": "gldas_sm"}

    async def embed(self, query: str) -> list[str] | None:
        if not self.enabled:
            return None
        hit = self.synonyms.get(query.casefold())
        return [hit] if hit else []


def seed_catalog(search: MemorySearch | None = None, cache=None) -> CatalogService:
    potentials = [
        TrendPotential(
            region_id="ukraine_south",
            variable_id="gldas_sm",
            season="JJA",
            p_significant=0.82,
            expected_sign=-1,
            reasons=("arid_climate",),
        )
    ]
    return CatalogService(
        passports=curated_passports(),
        regions=curated_regions(),
        potentials=potentials,
        demos=seed_demos(),
        glossary=seed_glossary(),
        links=curated_links(),
        events=curated_events(),
        search=search or MemorySearch(),
        cache=cache,
    )
