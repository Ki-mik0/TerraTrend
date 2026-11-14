import pytest

from earthtrend.api.application.story.service import (
    DRAFT_REJECTED,
    StoryService,
    story_from_json,
    story_key,
    story_to_json,
)
from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.domain.story.model import Draft, StoryError, StoryFacts, template_text
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.shared.cache import MemoryCache
from earthtrend.api.infrastructure.story.wiring import build_story_service


class ScriptedNarrator:
    """Writes `text`, or by default a sentence with the real slope of the facts."""

    def __init__(self, text: str | None = None, source: str = "model") -> None:
        self.text = text
        self.source = source
        self.calls = 0

    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        self.calls += 1
        return Draft(self.text or f"Нахил {facts.slope_decade} за десятиліття.", self.source)


async def _world(narrator=None, cache=None, demo=None):
    store = MemoryCaseStore()
    cases = build_case_service(store=store)
    narrator = narrator or ScriptedNarrator()
    service = build_story_service(
        cases=store, catalog=seed_catalog(), narrator=narrator, cache=cache or MemoryCache(), demo_texts=demo
    )
    case = await cases.create(
        spec=CaseSpec("merra2_t2m", "ukraine_south", "2000-01", "2025-12"), owner_id="u1", role="user"
    )
    return service, cases, case, narrator


async def test_case_story_follows_the_case_and_is_cached() -> None:
    service, _, case, narrator = await _world()
    story = await service.for_case(case.id, actor_id="u1", role="user", language="uk")
    assert (story.source, story.cached, story.warnings) == ("model", False, [])
    assert story.facts.variable_id == "merra2_t2m" and story.facts.direction == "increasing"
    assert story.facts.pattern == "warming" and story.title == "Air temperature · Ukraine south: потепління"
    assert story.facts.slope_decade == case.series.slope_decade
    assert set(story.facts.versions) == {"ruleset", "catalog", "datasets", "algorithm"}

    again = await service.for_case(case.id, actor_id="u1", role="user", language="uk")
    assert (again.source, again.cached, again.id, again.text) == ("cache", True, story.id, story.text)
    assert narrator.calls == 1
    await service.for_case(case.id, actor_id="u1", role="user", language="en")
    assert narrator.calls == 2


async def test_bad_draft_falls_back_to_the_facts_template() -> None:
    service, _, case, _ = await _world(ScriptedNarrator("Вигадане число 9.99"))
    story = await service.for_case(case.id, actor_id="u1", role="user")
    assert story.text == template_text(story.facts, "uk")
    assert (story.source, story.warnings) == ("template", [DRAFT_REJECTED])
    assert story.uses_only_fact_numbers()


async def test_privacy_and_readiness() -> None:
    service, cases, case, _ = await _world()
    with pytest.raises(StoryError) as caught:
        await service.for_case(case.id, actor_id="u2", role="user")
    assert caught.value.code == "case_not_found"
    assert (await service.for_case(case.id, actor_id="admin", role="admin")).case_id == case.id
    with pytest.raises(StoryError) as caught:
        await service.for_case("missing", actor_id="u1", role="user", language="en")
    assert caught.value.message == "Case not found"

    queued = await cases.create(
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12", heavy=True), owner_id="u1", role="user"
    )
    with pytest.raises(StoryError) as caught:
        await service.for_case(queued.id, actor_id="u1", role="user")
    assert caught.value.code == "data_not_ready"
    with pytest.raises(StoryError) as caught:
        await service.for_case(case.id, actor_id="u1", role="user", language="fr")
    assert caught.value.code == "language_unknown"


async def test_demo_text_is_served_without_the_narrator() -> None:
    service, _, case, narrator = await _world(demo={})
    demo_service, _, demo_case, demo_narrator = await _world()
    texts = {demo_case.id: {"en": "Demo text."}}
    demo_service._demo = texts
    story = await demo_service.for_case(demo_case.id, actor_id="u1", role="user", language="en")
    assert (story.text, story.source, story.cached) == ("Demo text.", "demo", True)
    assert demo_narrator.calls == 0
    assert (await demo_service.for_case(demo_case.id, actor_id="u1", role="user", language="uk")).source == "model"
    del service, case, narrator


async def test_spec_story_checks_the_catalog_first() -> None:
    service, _, _, narrator = await _world()
    story = await service.for_spec(variable_id="gldas_sm", region_id="ukraine_south", language="en")
    assert story.case_id is None and story.facts.pattern == "drying"
    assert [item.variable_id for item in story.facts.related][0] == "merra2_t2m"
    for variable_id, region_id, code in (("nope", "ukraine_south", "variable_not_found"), ("gldas_sm", "mars", "region_not_found")):
        with pytest.raises(StoryError) as caught:
            await service.for_spec(variable_id=variable_id, region_id=region_id, language="uk")
        assert caught.value.code == code
    assert narrator.calls == 1


async def test_service_without_catalog_or_cache() -> None:
    store = MemoryCaseStore()
    narrator = ScriptedNarrator()
    plain = StoryService(cases=store, facts=build_story_service(cases=store)._facts, narrator=narrator)
    first = await plain.for_spec(variable_id="gldas_sm", region_id="ukraine_north", language="uk")
    second = await plain.for_spec(variable_id="gldas_sm", region_id="ukraine_north", language="uk")
    assert first.source == second.source == "model" and narrator.calls == 2
    assert first.facts.variable_name == "" and first.facts.pattern == "drying"


async def test_spec_without_analytics_product_is_not_ready() -> None:
    service, _, _, narrator = await _world()
    with pytest.raises(StoryError) as caught:
        await service.for_spec(variable_id="merra2_t2m", region_id="ukraine_north", language="uk")
    assert caught.value.code == "data_not_ready" and narrator.calls == 0


def test_cache_key_and_codec() -> None:
    facts = StoryFacts("v", "r", "increasing", 0.1, "warming", versions={"analytics": "a2"})
    assert story_key(facts, language="en", case_id=None) == "story:v1:v:r:spec:en:analytics=a2"
    assert story_key(facts, language="uk", case_id="case_1").endswith(":case_1:uk:analytics=a2")
    from earthtrend.api.domain.story.model import Story

    story = Story(id="s1", language="en", text="t", facts=facts, title="T", source="model", warnings=["w"])
    assert story_from_json(story_to_json(story)) == story
