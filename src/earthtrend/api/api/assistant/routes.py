"""Assistant HTTP routes: ask, stream, and the caller's history."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import JSONBody, Parameter, PathParameter
from litestar.response.sse import ServerSentEvent, ServerSentEventMessage

from earthtrend.api.api.assistant.schemas import (
    AskRequest,
    AskResponse,
    ExchangeListResponse,
    ExchangeResponse,
    ask_response,
    exchange_response,
)
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.assistant.service import AssistantService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.assistant.exchange import ExchangeError

_STATUS = {"rate_limited": 429, "exchange_not_found": 404}


def _http(error: ExchangeError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 400), detail={"code": error.code, "message": error.message}
    )


def assistant_router(service: AssistantService, identity: IdentityService) -> Router:
    @post("/ask")
    async def ask(data: JSONBody[AskRequest], request: Request) -> AskResponse:
        actor = await require_actor(request, identity)
        try:
            exchange = await service.ask(
                question=data.question, language=data.language, role=actor.role, owner_id=actor.id, mode=data.mode
            )
        except ExchangeError as error:
            raise _http(error) from error
        return ask_response(exchange)

    @post("/ask/stream")
    async def ask_stream(data: JSONBody[AskRequest], request: Request) -> ServerSentEvent:
        actor = await require_actor(request, identity)
        exchange = service.start(
            question=data.question, language=data.language, role=actor.role, owner_id=actor.id, mode=data.mode
        )
        try:
            await service.admit(exchange)
        except ExchangeError as error:
            raise _http(error) from error

        async def messages() -> AsyncIterator[ServerSentEventMessage]:
            try:
                async for event in service.events(exchange):
                    yield ServerSentEventMessage(
                        event=event["event"], data=json.dumps(event["data"], ensure_ascii=False, default=str)
                    )
            except Exception:
                return

        return ServerSentEvent(messages(), status_code=200)

    @get("/exchanges")
    async def history(
        request: Request, limit: int = Parameter(default=20, ge=1, le=50)
    ) -> ExchangeListResponse:
        actor = await require_actor(request, identity)
        found = await service.history(owner_id=actor.id, role=actor.role, limit=limit)
        return ExchangeListResponse(exchanges=[exchange_response(item) for item in found])

    @get("/exchanges/{exchange_id:str}")
    async def one(exchange_id: Annotated[str, PathParameter()], request: Request) -> ExchangeResponse:
        actor = await require_actor(request, identity)
        try:
            found = await service.get(exchange_id, owner_id=actor.id)
        except ExchangeError as error:
            raise _http(error) from error
        return exchange_response(found)

    return Router(path="/api/v1/assistant", route_handlers=[ask, ask_stream, history, one])
