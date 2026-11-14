"""Narrators: M4 when one passed its gates, Claude when a key is set, the facts template always last."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from earthtrend.api.domain.story.model import (
    CORRELATION_CAVEAT,
    Draft,
    StoryFacts,
    facts_to_dict,
    template_text,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
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


class ClaudeNarrator:
    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self._model = model

    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        payload = facts_to_dict(facts)
        payload["caveats"] = list(facts.all_caveats())
        response = await self._client.beta.messages.create(
            model=self._model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Language: {language}.\nFacts: {json.dumps(payload, ensure_ascii=False)}",
                }
            ],
            output_config={"effort": "low"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if response.stop_reason in {"refusal", "max_tokens"}:
            raise ValueError(f"model stopped: {response.stop_reason}")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise ValueError("model returned no text")
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
        for narrator in self._narrators:
            try:
                return await narrator.write(language=language, facts=facts)
            except (anthropic.APIError, ValueError, KeyError, TypeError):
                continue
        return await self._last.write(language=language, facts=facts)


def narrator_from_env(*, m4: Any = None) -> ChainNarrator:
    """M4 goes first only when a gated M4 narrator is passed in; there is none in this build yet."""
    chain: list[Any] = [] if m4 is None else [m4]
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
        chain.append(ClaudeNarrator(anthropic.AsyncAnthropic(api_key=key, timeout=30.0, max_retries=2), model))
    return ChainNarrator(*chain)
