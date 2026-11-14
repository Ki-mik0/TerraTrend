from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from earthtrend.api.domain.assistant.exchange import ALLOWED_TOOLS, ToolStep, teach_answer_ok
from earthtrend.api.infrastructure.assistant import narrator as narrator_module
from earthtrend.api.infrastructure.assistant.narrator import (
    DEFAULT_MODEL,
    AnthropicNarrator,
    FallbackNarrator,
    TemplateNarrator,
    narrator_from_env,
    plan_schema,
)

CATALOG = {"gldas_sm", "merra2_t2m"}


def _response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", text=""), SimpleNamespace(type="text", text=text)],
    )


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


def _client(*replies) -> SimpleNamespace:
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(*replies)))


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


async def test_anthropic_plan_uses_structured_output_and_fallbacks() -> None:
    body = {"steps": [{"tool": "analyze_case", "reason": "тренд", "input": {"variable_id": "gldas_sm"}}]}
    client = _client(_response(json.dumps(body)))
    steps = await AnthropicNarrator(client, model="claude-test").plan(
        question="q", language="uk", mode="investigate", catalog_ids=CATALOG
    )
    assert steps == [ToolStep("analyze_case", "тренд", {"variable_id": "gldas_sm"})]
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and call["betas"] == [narrator_module.FALLBACK_BETA]


async def test_anthropic_answer_picks_system_prompt_by_mode() -> None:
    client = _client(_response("  Нахил 0.42.  "), _response("Чому?"))
    model = AnthropicNarrator(client)
    facts = [{"slope_decade": 0.42}]
    assert await model.answer(question="q", language="uk", mode="investigate", facts=facts, case_ids=["c"]) == (
        "Нахил 0.42."
    )
    await model.answer(question="q", language="uk", mode="teach", facts=facts, case_ids=["c"])
    systems = [call["system"] for call in client.beta.messages.calls]
    assert systems == [narrator_module.SYSTEM_INVESTIGATE, narrator_module.SYSTEM_TEACH]


@pytest.mark.parametrize("reply", [_response("x", "refusal"), _response("x", "max_tokens"), _response("  ")])
async def test_anthropic_rejects_refusal_truncation_and_empty_text(reply) -> None:
    with pytest.raises(ValueError):
        await AnthropicNarrator(_client(reply)).answer(
            question="q", language="uk", mode="investigate", facts=[], case_ids=[]
        )


def _api_error() -> anthropic.APIError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


async def test_fallback_uses_template_when_model_fails_or_is_missing() -> None:
    template = TemplateNarrator()
    broken = AnthropicNarrator(_client(_api_error(), _response("not json"), _api_error()))
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
    model = AnthropicNarrator(_client(_response(json.dumps(body)), _response("Готово.")))
    fallback = FallbackNarrator(TemplateNarrator(), model)
    assert [step.tool for step in await fallback.plan(question="q", language="uk", mode="investigate", catalog_ids=CATALOG)] == [
        "get_radar"
    ]
    assert await fallback.answer(question="q", language="uk", mode="investigate", facts=[], case_ids=[]) == "Готово."


def test_narrator_from_env(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert narrator_from_env()._model is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert narrator_from_env()._model._model == DEFAULT_MODEL
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert narrator_from_env()._model._model == "claude-sonnet-5-5"
