"""Ask the assistant: plan, run allowed tools, answer from their facts, keep the exchange."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from earthtrend.api.application.assistant.ports import (
    CaseFactsPort,
    CasePort,
    CatalogPort,
    Clock,
    ExchangeRepository,
    NarratorPort,
    NotePort,
    PlanCache,
    RadarPort,
    RateLimiter,
)
from earthtrend.api.domain.assistant.exchange import (
    CASE_TOOLS,
    AssistantExchange,
    ExchangeError,
    ToolStep,
    accept_plan,
    answer_stays_inside_facts,
    collect_numbers,
    fallback_answer,
    numbers_in,
    split_chunks,
    teach_answer_ok,
)
from earthtrend.api.domain.shared.numbers import with_roundings

Event = dict[str, Any]
Handler = Callable[[ToolStep, AssistantExchange], Awaitable[dict[str, Any]]]

HISTORY_LIMIT = 50


class _UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class AssistantService:
    def __init__(
        self,
        *,
        catalog: CatalogPort,
        cases: CasePort,
        evidence: CaseFactsPort,
        story: CaseFactsPort,
        radar: RadarPort,
        notes: NotePort,
        narrator: NarratorPort,
        profile: CaseFactsPort | None = None,
        urban: CaseFactsPort | None = None,
        exchanges: ExchangeRepository | None = None,
        plans: PlanCache | None = None,
        limiter: RateLimiter | None = None,
        clock: Clock | None = None,
        ids: Callable[[], str] | None = None,
    ) -> None:
        self._catalog = catalog
        self._cases = cases
        self._radar = radar
        self._notes = notes
        self._narrator = narrator
        self._exchanges = exchanges
        self._plans = plans
        self._limiter = limiter
        self._clock = clock or _UtcClock()
        self._ids = ids or (lambda: f"ask_{uuid.uuid4().hex[:16]}")
        self._handlers: dict[str, Handler] = {
            "search_variables": self._search_variables,
            "get_variable": self._get_variable,
            "search_regions": self._search_regions,
            "analyze_case": self._analyze_case,
            "compare_cases": self._compare_cases,
            "get_radar": self._get_radar,
            "get_evidence": self._case_facts(evidence),
            "get_story": self._case_facts(story),
            "get_profile": self._case_facts(profile or evidence),
            "get_urban": self._case_facts(urban or evidence),
        }

    def start(
        self, *, question: str, language: str, role: str, owner_id: str = "", mode: str = "investigate"
    ) -> AssistantExchange:
        return AssistantExchange(
            question=question,
            language=language,
            role=role,
            owner_id=owner_id,
            mode=mode,
            id=self._ids(),
            created_at=self._clock.now(),
        )

    async def ask(
        self, *, question: str, language: str, role: str, owner_id: str = "", mode: str = "investigate"
    ) -> AssistantExchange:
        exchange = self.start(question=question, language=language, role=role, owner_id=owner_id, mode=mode)
        await self.admit(exchange)
        async for _event in self.events(exchange):
            pass
        return exchange

    async def admit(self, exchange: AssistantExchange) -> None:
        if self._limiter is not None and not await self._limiter.allow(exchange.owner_id or "anonymous"):
            raise ExchangeError("rate_limited", exchange.language)

    async def history(self, *, owner_id: str, role: str, limit: int = 20) -> list[AssistantExchange]:
        if self._exchanges is None or role == "guest":
            return []
        return await self._exchanges.list(owner_id=owner_id, limit=max(1, min(limit, HISTORY_LIMIT)))

    async def get(self, exchange_id: str, *, owner_id: str, language: str = "uk") -> AssistantExchange:
        found = None if self._exchanges is None else await self._exchanges.get(exchange_id, owner_id=owner_id)
        if found is None:
            raise ExchangeError("exchange_not_found", language)
        return found

    async def events(self, exchange: AssistantExchange) -> AsyncIterator[Event]:
        try:
            async for event in self._run(exchange):
                yield event
        except Exception:
            exchange.fail()
            yield {"event": "error", "data": {"exchange_id": exchange.id, "code": "internal_error"}}
            raise
        finally:
            if exchange.status == "running":
                exchange.fail()
            if self._exchanges is not None and exchange.writes_note:
                await self._exchanges.save(exchange)

    async def _run(self, exchange: AssistantExchange) -> AsyncIterator[Event]:
        catalog_ids = await self._catalog.ids()
        region_ids = await self._catalog.region_ids()
        proposed = await self._plan(exchange, catalog_ids)
        exchange.steps = accept_plan(exchange, proposed, catalog_ids, region_ids)
        yield {
            "event": "plan",
            "data": {
                "exchange_id": exchange.id,
                "mode": exchange.mode,
                "steps": [step.payload() for step in exchange.steps],
                "warnings": list(exchange.warnings),
            },
        }

        facts: list[dict[str, Any]] = []
        for step in exchange.steps:
            prepared = _bind_case(step, exchange.case_ids[-1] if exchange.case_ids else None)
            if prepared is None:
                exchange.warn("case_required", tool=step.tool)
                yield {"event": "tool_skipped", "data": {**step.payload(), "code": "case_required"}}
                continue
            yield {"event": "tool_start", "data": prepared.payload()}
            result = await self._handlers[prepared.tool](prepared, exchange)
            if result.get("error"):
                exchange.warn("tool_failed", tool=prepared.tool, value=result["error"])
            else:
                self._remember(result, exchange)
            facts.append(result)
            yield {"event": "tool_result", "data": result}

        answer = await self._answer(exchange, facts)
        exchange.finish(answer)
        for chunk in split_chunks(answer):
            yield {"event": "answer_chunk", "data": {"text": chunk}}

        if exchange.writes_note:
            await self._notes.write(
                question=exchange.question,
                plan=exchange.steps,
                case_ids=exchange.case_ids,
                author_id=exchange.owner_id,
                role=exchange.role,
            )
        yield {
            "event": "done",
            "data": {
                "exchange_id": exchange.id,
                "case_ids": list(exchange.case_ids),
                "citations": list(exchange.citations),
                "warnings": list(exchange.warnings),
            },
        }

    async def _plan(self, exchange: AssistantExchange, catalog_ids: set[str]) -> list[ToolStep]:
        key = plan_key(exchange, catalog_ids)
        if self._plans is not None:
            cached = await self._plans.get(key)
            if cached is not None:
                return cached
        proposed = await self._narrator.plan(
            question=exchange.question, language=exchange.language, mode=exchange.mode, catalog_ids=catalog_ids
        )
        if self._plans is not None and proposed:
            await self._plans.put(key, proposed)
        return proposed

    async def _answer(self, exchange: AssistantExchange, facts: list[dict[str, Any]]) -> str:
        draft = await self._narrator.answer(
            question=exchange.question,
            language=exchange.language,
            mode=exchange.mode,
            facts=facts,
            case_ids=exchange.case_ids,
        )
        if exchange.mode == "teach" and not teach_answer_ok(draft):
            exchange.warn("teach_rejected")
            return fallback_answer(exchange)
        allowed = with_roundings(collect_numbers(facts)) | numbers_in(exchange.question)
        if not draft.strip() or not answer_stays_inside_facts(draft, allowed):
            exchange.warn("answer_outside_facts")
            return fallback_answer(exchange)
        return draft

    def _remember(self, result: dict[str, Any], exchange: AssistantExchange) -> None:
        case_id = result.get("case_id")
        if isinstance(case_id, str) and case_id:
            exchange.add_case(case_id)
            citation = {"case_id": case_id}
            for key in ("variable_id", "region_id", "version"):
                if result.get(key) is not None:
                    citation[key] = result[key]
            exchange.cite(citation)

    async def _search_variables(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        del exchange
        return {"tool": step.tool, "variables": await self._catalog.search_variables(str(step.input.get("q", "")))}

    async def _get_variable(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        del exchange
        variable = await self._catalog.get_variable(str(step.input.get("variable_id", "")))
        if variable is None:
            return {"tool": step.tool, "error": "variable_not_found"}
        return {"tool": step.tool, "variable": variable}

    async def _search_regions(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        del exchange
        return {"tool": step.tool, "regions": await self._catalog.search_regions(str(step.input.get("q", "")))}

    async def _analyze_case(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        if not step.input.get("variable_id") or not step.input.get("region_id"):
            return {"tool": step.tool, "error": "case_spec_incomplete"}
        created = await self._cases.analyze(
            variable_id=str(step.input["variable_id"]),
            region_id=str(step.input["region_id"]),
            season=step.input.get("season"),
            owner_id=exchange.owner_id,
            role=exchange.role,
        )
        return {"tool": step.tool, **created}

    async def _compare_cases(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        requested = [str(item) for item in step.input.get("case_ids") or []]
        case_ids = requested or list(exchange.case_ids)
        if len(case_ids) < 2:
            return {"tool": step.tool, "error": "compare_needs_two_cases"}
        body = await self._cases.compare(case_ids, owner_id=exchange.owner_id, role=exchange.role)
        return {"tool": step.tool, **body}

    async def _get_radar(self, step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
        del exchange
        return {"tool": step.tool, "items": await self._radar.feed()}

    @staticmethod
    def _case_facts(port: CaseFactsPort) -> Handler:
        async def handle(step: ToolStep, exchange: AssistantExchange) -> dict[str, Any]:
            body = await port.get(str(step.input["case_id"]), owner_id=exchange.owner_id, role=exchange.role)
            return {"tool": step.tool, **body}

        return handle


def plan_key(exchange: AssistantExchange, catalog_ids: set[str]) -> str:
    raw = json.dumps(
        [" ".join(exchange.question.casefold().split()), exchange.language, exchange.mode, sorted(catalog_ids)],
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bind_case(step: ToolStep, last_case_id: str | None) -> ToolStep | None:
    if step.tool not in CASE_TOOLS:
        return step
    case_id = step.input.get("case_id") or last_case_id
    if not case_id:
        return None
    return ToolStep(tool=step.tool, reason=step.reason, input={**step.input, "case_id": case_id})
