from __future__ import annotations

import json

import httpx
import pytest

from earthtrend.api.domain.assistant.exchange import ALLOWED_TOOLS, ToolStep, teach_answer_ok
from earthtrend.api.infrastructure.assistant import narrator as narrator_module
from earthtrend.api.infrastructure.assistant.narrator import (
    DEFAULT_MODEL,
    FallbackNarrator,
    OpenRouterNarrator,
    TemplateNarrator,
    narrator_from_env,
    plan_schema,
)
from earthtrend.api.infrastructure.shared.openrouter import OpenRouter

CATALOG = {"gldas_sm", "merra2_t2m"}


def _completion(text: str, finish: str = "stop") -> dict:
    return {"choices": [{"finish_reason": finish, "message": {"content": text}}]}


class FakePost:
    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def __call__(self, body: dict) -> dict:
        self.calls.append(body)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _router(*replies, model: str = "anthropic/claude-sonnet-4.5") -> tuple[OpenRouter, FakePost]:
    post = FakePost(*replies)
    return OpenRouter("test-key", model, post=post), post


async def test_template_plan_reads_variable_and_season_from_question() -> None:
    template = TemplateNarrator()
    steps = await template.plan(question="Чи спекотніше взимку?", language="uk", mode="investigate", catalog_ids=CATALOG)
    analyze = steps[1].input
    assert (analyze["variable_id"], analyze["season"]) == ("merra2_t2m", "DJF")
    assert [step.tool for step in steps] == ["search_variables", "analyze_case", "get_evidence", "get_story"]

    teach = await template.plan(question="Is the soil drying?", language="en", mode="teach", catalog_ids={"x_var"})
    assert teach[1].input == {"variable_id": "x_var", "region_id": "ukraine_south", "season": "JJA"}
    assert teach[0].reason == "Find the variable" and len(teach) == 3
    assert await template.plan(question="q", language="uk", mode="investigate", catalog_ids=set()) == []


async def test_template_answer_uses_only_facts() -> None:
    template = TemplateNarrator()
    facts = [{"tool": "analyze_case", "case_id": "case_1", "verdict": "strong", "slope_decade": -0.03}]
    uk = await template.answer(question="q", language="uk", mode="investigate", facts=facts, case_ids=["case_1"])
    assert "-0.03" in uk and "strong" in uk and "case_1" in uk
    en = await template.answer(question="q", language="en", mode="investigate", facts=facts, case_ids=["case_1"])
    assert en.startswith("Case case_1.") and "-0.03" in en
    bare = await template.answer(
        question="q", language="en", mode="investigate", facts=[{"error": "x", "verdict": "y"}], case_ids=["c"]
    )
    assert bare == "Case c. Open the case to check every piece of evidence."
    uk_bare = await template.answer(question="q", language="uk", mode="investigate", facts=[], case_ids=["c"])
    assert uk_bare == "Справа c. Відкрийте справу, щоб перевірити кожен доказ."
    assert await template.answer(question="q", language="uk", mode="investigate", facts=[], case_ids=[]) == (
        "Недостатньо доказів у каталозі."
    )
    teach = await template.answer(question="q", language="en", mode="teach", facts=facts, case_ids=["case_1"])
    assert teach_answer_ok(teach)


def test_plan_schema_limits_tools_and_variables() -> None:
    schema = plan_schema(CATALOG)
    item = schema["properties"]["steps"]["items"]
    assert item["properties"]["tool"]["enum"] == sorted(ALLOWED_TOOLS)
    assert item["properties"]["input"]["properties"]["variable_id"]["enum"] == sorted(CATALOG)
    assert "enum" not in plan_schema(set())["properties"]["steps"]["items"]["properties"]["input"]["properties"][
        "variable_id"
    ]


async def test_openrouter_plan_asks_for_the_tool_schema() -> None:
    body = {"steps": [{"tool": "analyze_case", "reason": "тренд", "input": {"variable_id": "gldas_sm"}}]}
    router, post = _router(_completion(json.dumps(body)), model="claude-test")
    steps = await OpenRouterNarrator(router).plan(
        question="q", language="uk", mode="investigate", catalog_ids=CATALOG
    )
    assert steps == [ToolStep("analyze_case", "тренд", {"variable_id": "gldas_sm"})]
    call = post.calls[0]
    assert call["model"] == "claude-test"
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["schema"]["properties"]["steps"]["items"]["properties"]["tool"]["enum"]


async def test_openrouter_answer_picks_system_prompt_by_mode() -> None:
    router, post = _router(_completion("  Нахил 0.42.  "), _completion("Чому?"))
    model = OpenRouterNarrator(router)
    facts = [{"slope_decade": 0.42}]
    assert await model.answer(question="q", language="uk", mode="investigate", facts=facts, case_ids=["c"]) == (
        "Нахил 0.42."
    )
    await model.answer(question="q", language="uk", mode="teach", facts=facts, case_ids=["c"])
    systems = [call["messages"][0]["content"] for call in post.calls]
    assert systems == [narrator_module.SYSTEM_INVESTIGATE, narrator_module.SYSTEM_TEACH]


@pytest.mark.parametrize(
    "reply",
    [_completion("x", "content_filter"), _completion("x", "length"), _completion("  ")],
)
async def test_openrouter_rejects_refusal_truncation_and_empty_text(reply) -> None:
    router, _post = _router(reply)
    with pytest.raises(ValueError):
        await OpenRouterNarrator(router).answer(
            question="q", language="uk", mode="investigate", facts=[], case_ids=[]
        )


def _api_error() -> httpx.ConnectError:
    return httpx.ConnectError("down")


async def test_fallback_uses_template_when_model_fails_or_is_missing() -> None:
    template = TemplateNarrator()
    router, _post = _router(_api_error(), _completion("not json"), _api_error())
    broken = OpenRouterNarrator(router)
    fallback = FallbackNarrator(template, broken)
    planned = await fallback.plan(question="soil", language="en", mode="investigate", catalog_ids=CATALOG)
    assert planned[1].input["variable_id"] == "gldas_sm"
    planned = await fallback.plan(question="soil", language="en", mode="investigate", catalog_ids=CATALOG)
    assert planned[0].tool == "search_variables"
    answer = await fallback.answer(question="q", language="en", mode="investigate", facts=[], case_ids=[])
    assert answer == "Not enough evidence in the catalog."

    offline = FallbackNarrator(template, None)
    assert await offline.plan(question="q", language="uk", mode="teach", catalog_ids=CATALOG)
    assert await offline.answer(question="q", language="uk", mode="teach", facts=[], case_ids=[])


async def test_fallback_returns_model_output_when_it_works() -> None:
    body = {"steps": [{"tool": "get_radar", "reason": "r", "input": {}}]}
    router, _post = _router(_completion(json.dumps(body)), _completion("Готово."))
    model = OpenRouterNarrator(router)
    fallback = FallbackNarrator(TemplateNarrator(), model)
    assert [step.tool for step in await fallback.plan(question="q", language="uk", mode="investigate", catalog_ids=CATALOG)] == [
        "get_radar"
    ]
    assert await fallback.answer(question="q", language="uk", mode="investigate", facts=[], case_ids=[]) == "Готово."


def test_narrator_from_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert narrator_from_env()._model is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert narrator_from_env()._model._model == DEFAULT_MODEL
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
    assert narrator_from_env()._model._model == "anthropic/claude-sonnet-4.5"
