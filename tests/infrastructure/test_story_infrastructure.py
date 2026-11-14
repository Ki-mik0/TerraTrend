"""Story facts from real cases, the narrator chain, and the story cache on memory and on real Redis."""

from __future__ import annotations

import os
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.domain.story.model import Draft, StoryFacts, RelatedVariable, numbers_in, template_text
from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis, MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.shared.cache import RedisCache
from earthtrend.api.infrastructure.story import narrators as narrator_module
from earthtrend.api.infrastructure.story.facts import CaseFacts, CatalogStoryCheck
from earthtrend.api.infrastructure.story.knowledge import pattern_for
from earthtrend.api.infrastructure.story.narrators import (
    DEFAULT_MODEL,
    ChainNarrator,
    ClaudeNarrator,
    TemplateNarrator,
    narrator_from_env,
)
from earthtrend.api.infrastructure.story.wiring import build_story_service, story_from_env

FACTS = StoryFacts(
    "gldas_sm", "ukraine_south", "decreasing", -0.21, "drying", related=(RelatedVariable("merra2_t2m", "driver"),)
)


async def _case(variable_id: str = "gldas_sm", region_id: str = "ukraine_south", heavy: bool = False):
    store = MemoryCaseStore()
    cases = build_case_service(store=store)
    case = await cases.create(
        spec=CaseSpec(variable_id, region_id, "2000-01", "2025-12", heavy=heavy), owner_id="u1", role="user"
    )
    return store, case


async def test_case_facts_follow_the_real_case() -> None:
    _, case = await _case("merra2_t2m")
    facts = await CaseFacts(MemoryAnalysis(), seed_catalog()).for_case(case)
    assert (facts.variable_id, facts.direction, facts.pattern) == ("merra2_t2m", "increasing", "warming")
    assert facts.slope_decade == case.series.slope_decade
    assert facts.alibi == (case.evidence.alibi.b_raw, case.evidence.alibi.b_adjusted)
    assert facts.witnesses == (case.evidence.witnesses.confirmed, case.evidence.witnesses.total)
    assert facts.versions["algorithm"] == case.algorithm_version and facts.versions["ruleset"] == case.verdict.ruleset
    assert (facts.variable_name, facts.region_name) == ("Air temperature", "Ukraine south")
    assert facts.papers and facts.related


async def test_case_facts_add_series_caveats_and_refuse_unfinished_cases() -> None:
    _, case = await _case()
    case.warnings = ["many_gaps"]
    case.series = type(case.series)(
        slope_decade=case.series.slope_decade,
        split=type(case.series.split)(split_flag=True, sig_pos=0.2, sig_neg=0.3),
        jackknife=type(case.series.jackknife)(influential_year=2010),
    )
    facts = await CaseFacts(MemoryAnalysis()).for_case(case)
    assert facts.caveats == ("many_gaps", "split_region", "influential_year")
    assert (facts.variable_name, facts.region_name) == ("", "")

    _, queued = await _case(heavy=True)
    with pytest.raises(ValueError):
        await CaseFacts(MemoryAnalysis()).for_case(queued)


async def test_spec_facts_and_catalog_check() -> None:
    catalog = seed_catalog()
    facts = await CaseFacts(MemoryAnalysis(), catalog).for_spec(variable_id="gldas_sm", region_id="ukraine_north")
    assert facts.direction == "decreasing" and facts.region_name == "Ukraine north"
    check = CatalogStoryCheck(catalog)
    assert await check.has_variable("gldas_sm") and not await check.has_variable("nope")
    assert await check.has_region("ukraine_south") and not await check.has_region("mars")
    assert pattern_for("unknown", "increasing") == "no_clear_pattern"


def _response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


class FakeMessages:
    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _client(*replies):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(*replies)))


async def test_claude_narrator_sends_facts_and_adds_the_causation_caveat() -> None:
    client = _client(_response("Ґрунт сохне: -0.21 за десятиліття."), _response("Correlation is not causation here."))
    claude = ClaudeNarrator(client, model="claude-test")
    draft = await claude.write(language="uk", facts=FACTS)
    assert draft == Draft("Ґрунт сохне: -0.21 за десятиліття. Кореляція не є причинністю.", "model")
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-test" and call["fallbacks"] == "default"
    assert "correlation_not_causation" in call["messages"][0]["content"]
    assert (await claude.write(language="en", facts=FACTS)).text == "Correlation is not causation here."

    plain = StoryFacts("v", "r", "increasing", 0.5, "warming")
    english = await ClaudeNarrator(_client(_response("Warming."))).write(language="en", facts=plain)
    assert english.text == "Warming."


@pytest.mark.parametrize("reply", [_response("x", "refusal"), _response("x", "max_tokens"), _response("  ")])
async def test_claude_narrator_rejects_unusable_replies(reply) -> None:
    with pytest.raises(ValueError):
        await ClaudeNarrator(_client(reply)).write(language="uk", facts=FACTS)


async def test_chain_tries_in_order_and_ends_with_the_template() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    failing = ClaudeNarrator(_client(anthropic.APIConnectionError(request=request)))

    class M4:
        async def write(self, *, language, facts):
            return Draft("M4 text", "m4")

    assert (await ChainNarrator(failing, M4()).write(language="uk", facts=FACTS)).source == "m4"
    fallback = await ChainNarrator(ClaudeNarrator(_client(_response("", "refusal")))).write(language="en", facts=FACTS)
    assert fallback == Draft(template_text(FACTS, "en"), "template")
    assert (await TemplateNarrator().write(language="uk", facts=FACTS)).source == "template"
    assert numbers_in(fallback.text) <= FACTS.allowed_numbers()


def test_narrator_from_env(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert narrator_from_env()._narrators == ()
    m4 = TemplateNarrator()
    assert narrator_from_env(m4=m4)._narrators == (m4,)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert narrator_from_env()._narrators[0]._model == DEFAULT_MODEL
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert narrator_from_env()._narrators[0]._model == "claude-sonnet-5-5"
    assert narrator_module.FALLBACK_BETA.startswith("server-side-fallback")


def test_story_from_env_uses_redis_when_configured(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    store = MemoryCaseStore()
    assert not isinstance(story_from_env(cases=store)._cache.inner, RedisCache)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    assert isinstance(story_from_env(cases=store, catalog=seed_catalog())._cache.inner, RedisCache)


async def test_story_cache_on_real_redis() -> None:
    redis_cache = RedisCache(Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/15"), decode_responses=True))
    try:
        await redis_cache._client.ping()
    except (RedisError, OSError) as error:
        await redis_cache._client.aclose()
        pytest.skip(f"Redis is not reachable: {error}")

    store, case = await _case()
    calls = []

    class Counting(TemplateNarrator):
        async def write(self, *, language, facts):
            calls.append(language)
            return await super().write(language=language, facts=facts)

    service = build_story_service(cases=store, catalog=seed_catalog(), narrator=Counting(), cache=redis_cache)
    first = await service.for_case(case.id, actor_id="u1", role="user", language="en")
    try:
        second = await service.for_case(case.id, actor_id="u1", role="user", language="en")
        assert (second.source, second.text, second.facts) == ("cache", first.text, first.facts)
        assert calls == ["en"]
    finally:
        keys = [key async for key in redis_cache._client.scan_iter(match=f"story:v1:*:{case.id}:*")]
        if keys:
            await redis_cache._client.delete(*keys)
        await redis_cache._client.aclose()
