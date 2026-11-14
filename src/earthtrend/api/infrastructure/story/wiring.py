"""Wire Story Lens: case facts, the narrator chain, the catalog check, and the shared cache."""

from __future__ import annotations

from typing import Any

from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.application.story.ports import CaseLookup, NarratorPort
from earthtrend.api.application.story.service import StoryService
from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis
from earthtrend.api.infrastructure.shared.cache import MemoryCache, cache_from_env
from earthtrend.api.infrastructure.story.facts import CaseFacts, CatalogStoryCheck
from earthtrend.api.infrastructure.story.narrators import narrator_from_env

DEMO_TEXTS: dict[str, dict[str, str]] = {
    "case_demo": {
        "uk": "Демо-справа: волога ґрунту на півдні України. Відкрий протокол, щоб побачити кожен доказ.",
        "en": "Demo case: soil moisture in southern Ukraine. Open the protocol to see every piece of evidence.",
    }
}


def build_story_service(
    *,
    cases: CaseLookup,
    catalog: CatalogService | None = None,
    narrator: NarratorPort | None = None,
    cache: CachePort | None = None,
    analysis: Any = None,
    demo_texts: dict[str, dict[str, str]] | None = None,
) -> StoryService:
    return StoryService(
        cases=cases,
        facts=CaseFacts(analysis or MemoryAnalysis(), catalog),
        narrator=narrator or narrator_from_env(),
        catalog=None if catalog is None else CatalogStoryCheck(catalog),
        cache=cache if cache is not None else MemoryCache(),
        demo_texts=DEMO_TEXTS if demo_texts is None else demo_texts,
    )


def story_from_env(
    *, cases: CaseLookup, catalog: CatalogService | None = None, cache: CachePort | None = None
) -> StoryService:
    """Redis cache when REDIS_URL is set, a TTL dict otherwise. `cache` shares the app-wide instance."""
    return build_story_service(cases=cases, catalog=catalog, cache=cache if cache is not None else cache_from_env())
