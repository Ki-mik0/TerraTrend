from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from earthtrend.api.application.assistant.service import AssistantService, plan_key
from earthtrend.api.domain.assistant.exchange import ExchangeError, ToolStep
from earthtrend.api.infrastructure.assistant.memory import (
    CASE_ID,
    MemoryCases,
    MemoryCatalog,
    MemoryEvidence,
    MemoryExchangeRepository,
    MemoryNotes,
    MemoryPlanCache,
    MemoryProfile,
    MemoryRadar,
    MemoryRateLimiter,
    MemoryStory,
    MemoryUrban,
)
from earthtrend.api.infrastructure.assistant.narrator import TemplateNarrator


class ScriptedNarrator:
    def __init__(self, steps: list[ToolStep], answer: str = "Справа case_mem_1: нахил 0.42.") -> None:
        self.steps = steps
        self.text = answer
        self.plan_calls = 0
        self.facts: list[dict[str, Any]] = []

    async def plan(self, *, question: str, language: str, mode: str, catalog_ids: set[str]) -> list[ToolStep]:
        self.plan_calls += 1
        return list(self.steps)

    async def answer(self, *, question, language, mode, facts, case_ids) -> str:
        self.facts = facts
        return self.text


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 14, tzinfo=UTC)

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


class BrokenCatalog(MemoryCatalog):
    async def ids(self) -> set[str]:
        raise RuntimeError("catalog down")


ANALYZE = ToolStep("analyze_case", "trend", {"variable_id": "gldas_sm", "region_id": "ukraine_south", "season": "JJA"})


def _service(narrator=None, **overrides) -> AssistantService:
    counter = iter(range(1, 1000))
    values = dict(
        catalog=MemoryCatalog(),
        cases=MemoryCases(),
        evidence=MemoryEvidence(),
        story=MemoryStory(),
        profile=MemoryProfile(),
        urban=MemoryUrban(),
        radar=MemoryRadar(),
        notes=MemoryNotes(),
        narrator=narrator or TemplateNarrator(),
        exchanges=MemoryExchangeRepository(),
        plans=MemoryPlanCache(),
        limiter=MemoryRateLimiter(),
        clock=StepClock(),
        ids=lambda: f"ask_{next(counter)}",
    )
    values.update(overrides)
    return AssistantService(**values)


async def test_user_writes_note_and_history_guest_does_not() -> None:
    notes, exchanges = MemoryNotes(), MemoryExchangeRepository()
    service = _service(notes=notes, exchanges=exchanges)
    user = await service.ask(question="Чи сохне ґрунт?", language="uk", role="user", owner_id="u1")
    assert user.status == "answered"
    assert user.case_ids == [CASE_ID]
    assert user.citations == [{"case_id": CASE_ID, "variable_id": "gldas_sm", "region_id": "ukraine_south"}]
    assert notes.notes[0]["case_ids"] == [CASE_ID]
    assert [item.id for item in await service.history(owner_id="u1", role="user")] == [user.id]
    assert (await service.get(user.id, owner_id="u1")).answer == user.answer

    guest = await service.ask(question="Чи сохне ґрунт?", language="uk", role="guest", owner_id="g1")
    assert guest.case_ids == [CASE_ID]
    assert len(notes.notes) == 1
    assert await service.history(owner_id="g1", role="guest") == []
    with pytest.raises(ExchangeError) as caught:
        await service.get(guest.id, owner_id="g1")
    assert caught.value.code == "exchange_not_found"


async def test_events_follow_the_contract() -> None:
    service = _service()
    exchange = service.start(question="Is the soil drying in summer?", language="en", role="user", owner_id="u1")
    events = [event async for event in service.events(exchange)]
    names = [event["event"] for event in events]
    assert names[0] == "plan" and names[-1] == "done"
    assert {"tool_start", "tool_result", "answer_chunk"} <= set(names)
    assert events[-1]["data"]["exchange_id"] == exchange.id
    text = "".join(event["data"]["text"] for event in events if event["event"] == "answer_chunk")
    assert text == exchange.answer
    assert "0.42" in text


async def test_unknown_tool_never_falls_through_to_radar() -> None:
    narrator = ScriptedNarrator([ToolStep("drop_table", "", {}), ANALYZE])
    exchange = await _service(narrator).ask(question="q", language="uk", role="user", owner_id="u1")
    assert [step.tool for step in exchange.steps] == ["analyze_case"]
    assert not any(fact["tool"] == "get_radar" for fact in narrator.facts)
    assert exchange.warnings == ["Інструмент drop_table не дозволений"]


async def test_case_tool_without_case_is_skipped() -> None:
    narrator = ScriptedNarrator([ToolStep("get_evidence", "", {})], answer="Без чисел.")
    service = _service(narrator)
    exchange = service.start(question="q", language="en", role="user", owner_id="u1")
    events = [event async for event in service.events(exchange)]
    assert any(event["event"] == "tool_skipped" for event in events)
    assert exchange.warnings == ["Step get_evidence needs a case, but no case exists yet"]
    assert exchange.answer == "Без чисел."


async def test_every_tool_runs_through_its_handler() -> None:
    steps = [
        ToolStep("search_variables", "", {"q": "soil"}),
        ToolStep("get_variable", "", {"variable_id": "gldas_sm"}),
        ToolStep("search_regions", "", {"q": "south"}),
        ANALYZE,
        ToolStep("get_evidence", "", {}),
        ToolStep("get_profile", "", {}),
        ToolStep("get_urban", "", {}),
        ToolStep("get_story", "", {"case_id": "case_other"}),
        ToolStep("compare_cases", "", {"case_ids": ["a", "b"]}),
        ToolStep("get_radar", "", {}),
    ]
    narrator = ScriptedNarrator(steps[:8])
    service = _service(narrator)
    await service.ask(question="q", language="uk", role="user", owner_id="u1")
    assert [fact["tool"] for fact in narrator.facts] == [step.tool for step in steps[:8]]
    assert narrator.facts[7]["case_id"] == "case_other"

    narrator = ScriptedNarrator(steps[8:])
    await _service(narrator).ask(question="q", language="uk", role="user", owner_id="u1")
    assert narrator.facts[0]["cases"][1]["case_id"] == "b"
    assert narrator.facts[1]["items"]


async def test_tool_errors_are_warnings_and_the_stream_continues() -> None:
    narrator = ScriptedNarrator(
        [
            ToolStep("get_variable", "", {"variable_id": "merra2_t2m"}),
            ToolStep("analyze_case", "", {"variable_id": "gldas_sm"}),
            ToolStep("compare_cases", "", {}),
            ANALYZE,
        ]
    )

    class NoTemperature(MemoryCatalog):
        async def get_variable(self, variable_id: str):
            return None

    exchange = await _service(narrator, catalog=NoTemperature()).ask(
        question="q", language="uk", role="user", owner_id="u1"
    )
    assert exchange.status == "answered"
    assert exchange.case_ids == [CASE_ID]
    assert [fact.get("error") for fact in narrator.facts[:3]] == [
        "variable_not_found",
        "case_spec_incomplete",
        "compare_needs_two_cases",
    ]
    assert len(exchange.warnings) == 3


async def test_compare_uses_cases_of_this_exchange() -> None:
    class TwoCases(MemoryCases):
        seq = 0

        async def analyze(self, **kwargs):
            TwoCases.seq += 1
            return {**await super().analyze(**kwargs), "case_id": f"case_{TwoCases.seq}"}

    narrator = ScriptedNarrator([ANALYZE, ANALYZE, ToolStep("compare_cases", "", {})], answer="Порівняно.")
    exchange = await _service(narrator, cases=TwoCases()).ask(question="q", language="uk", role="user", owner_id="u1")
    assert exchange.case_ids == ["case_1", "case_2"]
    assert [row["case_id"] for row in narrator.facts[2]["cases"]] == ["case_1", "case_2"]


async def test_number_outside_facts_falls_back_but_question_numbers_are_allowed() -> None:
    narrator = ScriptedNarrator([ANALYZE], answer="Нахил 0.99.")
    exchange = await _service(narrator).ask(question="q", language="uk", role="user", owner_id="u1")
    assert exchange.answer == f"Висновок зібрано лише з фактів справи {CASE_ID}."
    assert exchange.warnings == ["Відповідь містила число поза фактами"]

    narrator = ScriptedNarrator([ANALYZE], answer="З 2010 року нахил 0.42.")
    exchange = await _service(narrator).ask(question="Що з 2010 року?", language="uk", role="user", owner_id="u1")
    assert exchange.answer == "З 2010 року нахил 0.42."

    narrator = ScriptedNarrator([], answer="   ")
    exchange = await _service(narrator).ask(question="q", language="uk", role="user", owner_id="u1")
    assert exchange.answer == "Недостатньо доказів у каталозі."


async def test_teach_mode_asks_a_question_and_rejects_verdicts() -> None:
    narrator = ScriptedNarrator([ANALYZE], answer="Чому тренд міг змінитися після прибирання сезонності?")
    exchange = await _service(narrator).ask(question="q", language="uk", role="user", owner_id="u1", mode="teach")
    assert exchange.answer.endswith("?")

    narrator = ScriptedNarrator([ANALYZE], answer="Вирок: strong.")
    exchange = await _service(narrator).ask(question="q", language="en", role="user", owner_id="u1", mode="teach")
    assert exchange.answer.endswith("?")
    assert exchange.warnings == ["The teaching answer was not a question"]


async def test_plan_cache_skips_the_narrator() -> None:
    narrator = ScriptedNarrator([ANALYZE])
    plans = MemoryPlanCache()
    service = _service(narrator, plans=plans)
    await service.ask(question="Чи  СОХНЕ ґрунт?", language="uk", role="user", owner_id="u1")
    await service.ask(question="чи сохне ґрунт?", language="uk", role="user", owner_id="u2")
    assert narrator.plan_calls == 1
    await service.ask(question="чи сохне ґрунт?", language="uk", role="user", owner_id="u2", mode="teach")
    assert narrator.plan_calls == 2

    empty = ScriptedNarrator([])
    cache = MemoryPlanCache()
    await _service(empty, plans=cache).ask(question="q", language="uk", role="user", owner_id="u1")
    assert cache.items == {}


async def test_rate_limit_rejects_after_the_window_is_full() -> None:
    service = _service(limiter=MemoryRateLimiter(limit=1, now=lambda: 0.0))
    await service.ask(question="q", language="uk", role="user", owner_id="u1")
    with pytest.raises(ExchangeError) as caught:
        await service.ask(question="q", language="en", role="user", owner_id="u1")
    assert caught.value.code == "rate_limited"
    assert caught.value.message == "Too many questions. Try again in a minute"


async def test_failure_emits_error_and_persists_failed_status() -> None:
    exchanges = MemoryExchangeRepository()
    service = _service(catalog=BrokenCatalog(), exchanges=exchanges)
    exchange = service.start(question="q", language="uk", role="user", owner_id="u1")
    seen: list[str] = []
    with pytest.raises(RuntimeError):
        async for event in service.events(exchange):
            seen.append(event["event"])
    assert seen == ["error"]
    assert exchanges.items[exchange.id].status == "failed"


async def test_abandoned_stream_is_saved_as_failed() -> None:
    exchanges = MemoryExchangeRepository()
    service = _service(exchanges=exchanges)
    exchange = service.start(question="q", language="uk", role="user", owner_id="u1")
    stream = service.events(exchange)
    assert (await anext(stream))["event"] == "plan"
    await stream.aclose()
    assert exchanges.items[exchange.id].status == "failed"


async def test_service_works_without_optional_ports() -> None:
    service = AssistantService(
        catalog=MemoryCatalog(),
        cases=MemoryCases(),
        evidence=MemoryEvidence(),
        story=MemoryStory(),
        radar=MemoryRadar(),
        notes=MemoryNotes(),
        narrator=ScriptedNarrator([ANALYZE, ToolStep("get_profile", "", {})]),
    )
    exchange = await service.ask(question="q", language="uk", role="user", owner_id="u1")
    assert exchange.id.startswith("ask_") and exchange.created_at is not None
    assert await service.history(owner_id="u1", role="user") == []
    with pytest.raises(ExchangeError):
        await service.get(exchange.id, owner_id="u1")


async def test_history_limit_is_clamped_and_newest_first() -> None:
    service = _service()
    for _ in range(3):
        await service.ask(question="q", language="uk", role="user", owner_id="u1")
    found = await service.history(owner_id="u1", role="user", limit=0)
    assert [item.id for item in found] == ["ask_3"]
    found = await service.history(owner_id="u1", role="user", limit=500)
    assert [item.id for item in found] == ["ask_3", "ask_2", "ask_1"]


def test_plan_key_normalizes_question_and_depends_on_mode() -> None:
    service = _service()
    first = service.start(question="Чи  Сохне?", language="uk", role="user")
    second = service.start(question="чи сохне?", language="uk", role="user")
    teach = service.start(question="чи сохне?", language="uk", role="user", mode="teach")
    assert plan_key(first, {"a", "b"}) == plan_key(second, {"b", "a"})
    assert plan_key(first, {"a"}) != plan_key(teach, {"a"})
