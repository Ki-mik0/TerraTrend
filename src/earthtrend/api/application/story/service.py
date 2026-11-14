"""BuildStory: facts from analytics, text from a narrator, numbers checked, result cached by spec, language and versions."""

from __future__ import annotations

import hashlib
from typing import Any

from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.application.story.ports import CaseLookup, CatalogCheck, FactsPort, NarratorPort
from earthtrend.api.domain.story.model import (
    Story,
    StoryError,
    StoryFacts,
    facts_from_dict,
    facts_to_dict,
    keep_or_template,
    require_language,
    story_title,
)

CACHE_PREFIX = "story:v1:"
CACHE_TTL_SECONDS = 24 * 3600
DRAFT_REJECTED = "draft_rejected"


class StoryService:
    def __init__(
        self,
        *,
        cases: CaseLookup,
        facts: FactsPort,
        narrator: NarratorPort,
        catalog: CatalogCheck | None = None,
        cache: CachePort | None = None,
        demo_texts: dict[str, dict[str, str]] | None = None,
        ttl_seconds: int = CACHE_TTL_SECONDS,
    ) -> None:
        self._cases = cases
        self._facts = facts
        self._narrator = narrator
        self._catalog = catalog
        self._cache = cache
        self._demo = demo_texts or {}
        self._ttl = ttl_seconds

    async def for_case(self, case_id: str, *, actor_id: str, role: str, language: str = "uk") -> Story:
        require_language(language)
        case = await self._cases.get(case_id)
        if case is None or not case.visible_to(actor_id, role):
            raise StoryError("case_not_found", language=language)
        if case.status != "completed" or case.series is None:
            raise StoryError("data_not_ready", language=language)
        facts = await self._facts.for_case(case)
        demo = self._demo.get(case_id, {}).get(language)
        if demo is not None:
            return Story(
                id=f"story_{case_id}_{language}",
                language=language,
                text=demo,
                facts=facts,
                case_id=case_id,
                cached=True,
                title=story_title(facts, language),
                source="demo",
            )
        return await self._build(facts, language=language, case_id=case_id)

    async def for_spec(self, *, variable_id: str, region_id: str, language: str) -> Story:
        require_language(language)
        if self._catalog is not None:
            if not await self._catalog.has_variable(variable_id):
                raise StoryError("variable_not_found", language=language)
            if not await self._catalog.has_region(region_id):
                raise StoryError("region_not_found", language=language)
        facts = await self._facts.for_spec(variable_id=variable_id, region_id=region_id)
        return await self._build(facts, language=language, case_id=None)

    async def _build(self, facts: StoryFacts, *, language: str, case_id: str | None) -> Story:
        key = story_key(facts, language=language, case_id=case_id)
        if self._cache is not None:
            found = await self._cache.get_json(key)
            if found is not None:
                story = story_from_json(found)
                story.cached = True
                story.source = "cache"
                return story
        draft = await self._narrator.write(language=language, facts=facts)
        text, kept = keep_or_template(draft.text, facts, language)
        story = Story(
            id="story_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            language=language,
            text=text,
            facts=facts,
            case_id=case_id,
            title=story_title(facts, language),
            source=draft.source if kept else "template",
            warnings=[] if kept else [DRAFT_REJECTED],
        )
        if self._cache is not None:
            await self._cache.set_json(key, story_to_json(story), self._ttl)
        return story


def story_key(facts: StoryFacts, *, language: str, case_id: str | None) -> str:
    subject = case_id or "spec"
    return f"{CACHE_PREFIX}{facts.variable_id}:{facts.region_id}:{subject}:{language}:{facts.cache_tag()}"


def story_to_json(story: Story) -> dict[str, Any]:
    return {
        "id": story.id,
        "language": story.language,
        "text": story.text,
        "facts": facts_to_dict(story.facts),
        "case_id": story.case_id,
        "title": story.title,
        "source": story.source,
        "warnings": list(story.warnings),
    }


def story_from_json(body: dict[str, Any]) -> Story:
    return Story(
        id=body["id"],
        language=body["language"],
        text=body["text"],
        facts=facts_from_dict(body["facts"]),
        case_id=body.get("case_id"),
        title=body.get("title", ""),
        source=body.get("source", "template"),
        warnings=list(body.get("warnings", [])),
    )
