"""Narrators: a local template, and OpenRouter when a key is configured."""

from __future__ import annotations

import json
from typing import Any

import httpx

from earthtrend.api.domain.assistant.exchange import ALLOWED_TOOLS, ToolStep, message
from earthtrend.api.infrastructure.shared.openrouter import (
    DEFAULT_MODEL,
    OpenRouter,
    OpenRouterError,
    key_from_env,
    model_from_env,
)

_VARIABLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ґрунт", "сох", "посух", "волог", "soil", "drought", "dry"), "gldas_sm"),
    (("темпер", "спек", "тепл", "жар", "temperat", "heat", "warm"), "merra2_t2m"),
)
_SEASON_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("літ", "summer"), "JJA"),
    (("зим", "winter"), "DJF"),
    (("весн", "spring"), "MAM"),
    (("осін", "осен", "autumn", "fall"), "SON"),
)
DEFAULT_REGION = "ukraine_south"

SYSTEM_PLAN = (
    "You plan a climate-trend investigation for EarthTrend. You never compute or state numbers. "
    "Return only steps that call the allowed tools. Use variable ids strictly from the catalog list. "
    "Typical order: search_variables, search_regions, analyze_case, then get_evidence / get_profile / "
    "get_urban / get_story for that case, compare_cases when the question compares places or periods, "
    "get_radar for 'what is changing most' questions. At most 8 steps. Write each reason in the user's language."
)
SYSTEM_INVESTIGATE = (
    "You explain a climate-trend investigation to a student. Use only the facts given as JSON. "
    "Every number you write must appear in those facts exactly; never round or invent numbers. "
    "Name the case id for each conclusion. Say 'correlation is not causation' when you mention related variables. "
    "If facts are missing or contain errors, say the evidence is insufficient. At most 5 sentences."
)
SYSTEM_TEACH = (
    "You are a Socratic tutor. Using only the facts given as JSON, ask the student exactly one question that "
    "makes them reason about the evidence. Do not give the verdict, do not write verdict words, write no numbers. "
    "Reply with that single question only, ending with a question mark."
)


def _pick(question: str, hints: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    text = question.casefold()
    return next((value for words, value in hints if any(word in text for word in words)), None)


def _first_fact(facts: list[dict[str, Any]], key: str) -> Any:
    return next((item[key] for item in facts if item.get(key) is not None and not item.get("error")), None)


class TemplateNarrator:
    """Works without a network: picks a variable and season from words in the question."""

    async def plan(self, *, question: str, language: str, mode: str, catalog_ids: set[str]) -> list[ToolStep]:
        if not catalog_ids:
            return []
        hinted = _pick(question, _VARIABLE_HINTS)
        variable_id = hinted if hinted in catalog_ids else sorted(catalog_ids)[0]
        season = _pick(question, _SEASON_HINTS) or "JJA"
        uk = language == "uk"
        steps = [
            ToolStep("search_variables", "Знайти змінну в каталозі" if uk else "Find the variable", {"q": question}),
            ToolStep(
                "analyze_case",
                "Перевірити тренд у регіоні" if uk else "Check the trend in the region",
                {"variable_id": variable_id, "region_id": DEFAULT_REGION, "season": season},
            ),
            ToolStep("get_evidence", "Прочитати протокол доказів" if uk else "Read the evidence", {}),
        ]
        if mode == "investigate":
            steps.append(ToolStep("get_story", "Прочитати факти історії" if uk else "Read the story facts", {}))
        return steps

    async def answer(
        self, *, question: str, language: str, mode: str, facts: list[dict[str, Any]], case_ids: list[str]
    ) -> str:
        del question
        if mode == "teach":
            return message("teach_default", language)
        if not case_ids:
            return message("no_evidence", language)
        verdict = _first_fact(facts, "verdict") or _first_fact(facts, "verdict_code")
        slope = _first_fact(facts, "slope_decade")
        case_list = ", ".join(case_ids)
        if language == "en":
            parts = [f"Case {case_list}."]
            if verdict:
                parts.append(f"Verdict: {verdict}.")
            if slope is not None:
                parts.append(f"Slope per decade: {slope}.")
            parts.append("Open the case to check every piece of evidence.")
        else:
            parts = [f"Справа {case_list}."]
            if verdict:
                parts.append(f"Вирок: {verdict}.")
            if slope is not None:
                parts.append(f"Нахил за десятиліття: {slope}.")
            parts.append("Відкрийте справу, щоб перевірити кожен доказ.")
        return " ".join(parts)


def plan_schema(catalog_ids: set[str]) -> dict[str, Any]:
    variable: dict[str, Any] = {"type": "string"}
    if catalog_ids:
        variable["enum"] = sorted(catalog_ids)
    return {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": sorted(ALLOWED_TOOLS)},
                        "reason": {"type": "string"},
                        "input": {
                            "type": "object",
                            "properties": {
                                "q": {"type": "string"},
                                "variable_id": variable,
                                "region_id": {"type": "string"},
                                "season": {"type": "string", "enum": ["DJF", "MAM", "JJA", "SON"]},
                                "case_id": {"type": "string"},
                                "case_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": ["tool", "reason", "input"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }


class OpenRouterNarrator:
    def __init__(self, router: OpenRouter) -> None:
        self._router = router
        self._model = router.model

    async def plan(self, *, question: str, language: str, mode: str, catalog_ids: set[str]) -> list[ToolStep]:
        raw = await self._router.complete(
            system=SYSTEM_PLAN,
            user=f"Language: {language}. Mode: {mode}. Catalog variables: {sorted(catalog_ids)}.\nQuestion: {question}",
            json_schema=plan_schema(catalog_ids),
            max_tokens=4000,
        )
        payload = json.loads(raw)
        return [ToolStep(tool=item["tool"], reason=item["reason"], input=dict(item["input"])) for item in payload["steps"]]

    async def answer(
        self, *, question: str, language: str, mode: str, facts: list[dict[str, Any]], case_ids: list[str]
    ) -> str:
        return await self._router.complete(
            system=SYSTEM_TEACH if mode == "teach" else SYSTEM_INVESTIGATE,
            user=f"Language: {language}. Cases: {case_ids}.\nQuestion: {question}\n"
            f"Facts: {json.dumps(facts, ensure_ascii=False, default=str)}",
            max_tokens=4000,
        )


class FallbackNarrator:
    """Use OpenRouter when it is configured, and the template when it is not or the call fails."""

    def __init__(self, template: TemplateNarrator, model: OpenRouterNarrator | None) -> None:
        self._template = template
        self._model = model

    async def plan(self, *, question: str, language: str, mode: str, catalog_ids: set[str]) -> list[ToolStep]:
        if self._model is not None:
            try:
                return await self._model.plan(question=question, language=language, mode=mode, catalog_ids=catalog_ids)
            except (OpenRouterError, httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        return await self._template.plan(question=question, language=language, mode=mode, catalog_ids=catalog_ids)

    async def answer(
        self, *, question: str, language: str, mode: str, facts: list[dict[str, Any]], case_ids: list[str]
    ) -> str:
        if self._model is not None:
            try:
                return await self._model.answer(
                    question=question, language=language, mode=mode, facts=facts, case_ids=case_ids
                )
            except (OpenRouterError, httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        return await self._template.answer(
            question=question, language=language, mode=mode, facts=facts, case_ids=case_ids
        )


def narrator_from_env() -> FallbackNarrator:
    key = key_from_env()
    if not key:
        return FallbackNarrator(TemplateNarrator(), None)
    return FallbackNarrator(TemplateNarrator(), OpenRouterNarrator(OpenRouter(key, model_from_env())))
