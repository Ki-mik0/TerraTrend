"""Narrators: M4 when a series is present, OpenRouter when a key is set, the facts template last."""

from __future__ import annotations

import json
from typing import Any

import httpx

from earthtrend.api.domain.story.model import (
    CORRELATION_CAVEAT,
    Draft,
    StoryFacts,
    facts_to_dict,
    template_text,
)
from earthtrend.api.infrastructure.shared.openrouter import (
    DEFAULT_MODEL,
    OpenRouter,
    OpenRouterError,
    key_from_env,
    model_from_env,
)
SYSTEM = (
    "You write a short Story Lens for a climate-trend case for school students. Use only the facts given as JSON. "
    "Every number you write must appear in the facts exactly; never round, convert or invent numbers, and write no "
    "years or dates that are not in the facts. Explain the direction, the pattern, the co-participants and the alibi "
    "in plain words. If co-participants are listed, say that correlation is not causation. At most 6 sentences. "
    "Reply with the story text only."
)


class TemplateNarrator:
    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        return Draft(template_text(facts, language), "template")


class OpenRouterNarrator:
    def __init__(self, router: OpenRouter) -> None:
        self._router = router
        self._model = router.model

    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        payload = facts_to_dict(facts)
        payload["caveats"] = list(facts.all_caveats())
        text = await self._router.complete(
            system=SYSTEM,
            user=f"Language: {language}.\nFacts: {json.dumps(payload, ensure_ascii=False)}",
            max_tokens=4000,
        )
        if CORRELATION_CAVEAT in facts.all_caveats() and not _mentions_causation(text):
            text = f"{text} {'Кореляція не є причинністю.' if language == 'uk' else 'Correlation is not causation.'}"
        return Draft(text, "model")


def _mentions_causation(text: str) -> bool:
    lowered = text.casefold()
    return "причинн" in lowered or "causation" in lowered


class ChainNarrator:
    """Try each narrator in order; a failure moves to the next. The template never fails."""

    def __init__(self, *narrators: Any) -> None:
        self._narrators = narrators
        self._last = TemplateNarrator()

    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        if facts.lens_series is not None:
            from earthtrend.api.infrastructure.analytics_bridge import run_blocking, story_text

            text, source = await run_blocking(story_text, facts.lens_series, language)
            return Draft(text, source)
        for narrator in self._narrators:
            try:
                return await narrator.write(language=language, facts=facts)
            except (OpenRouterError, httpx.HTTPError, ValueError, KeyError, TypeError):
                continue
        return await self._last.write(language=language, facts=facts)


def narrator_from_env(*, m4: Any = None) -> ChainNarrator:
    """M4 goes first only when a gated M4 narrator is passed in; there is none in this build yet."""
    chain: list[Any] = [] if m4 is None else [m4]
    key = key_from_env()
    if key:
        chain.append(OpenRouterNarrator(OpenRouter(key, model_from_env())))
    return ChainNarrator(*chain)
