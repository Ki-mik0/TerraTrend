"""HTTP schemas for the assistant slice."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from earthtrend.api.domain.assistant.exchange import AssistantExchange


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["uk", "en"] = "uk"
    mode: Literal["investigate", "teach"] = "investigate"


class PlanStepResponse(BaseModel):
    tool: str
    reason: str
    input: dict[str, Any]


class AskResponse(BaseModel):
    exchange_id: str
    mode: str
    status: str
    answer: str
    plan: list[PlanStepResponse]
    case_ids: list[str]
    citations: list[dict[str, Any]]
    warnings: list[str]


class ExchangeResponse(AskResponse):
    question: str
    language: str
    created_at: datetime | None


class ExchangeListResponse(BaseModel):
    exchanges: list[ExchangeResponse]


def _plan(exchange: AssistantExchange) -> list[PlanStepResponse]:
    return [PlanStepResponse(tool=step.tool, reason=step.reason, input=step.input) for step in exchange.steps]


def ask_response(exchange: AssistantExchange) -> AskResponse:
    return AskResponse(
        exchange_id=exchange.id,
        mode=exchange.mode,
        status=exchange.status,
        answer=exchange.answer,
        plan=_plan(exchange),
        case_ids=list(exchange.case_ids),
        citations=list(exchange.citations),
        warnings=list(exchange.warnings),
    )


def exchange_response(exchange: AssistantExchange) -> ExchangeResponse:
    return ExchangeResponse(
        **ask_response(exchange).model_dump(),
        question=exchange.question,
        language=exchange.language,
        created_at=exchange.created_at,
    )
