"""Story HTTP routes."""

from __future__ import annotations

from typing import Literal

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery, JSONBody

from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.api.story.schemas import StoryRequest, StoryResponse, story_response
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.application.story.service import StoryService
from earthtrend.api.domain.story.model import StoryError

_STATUS = {"data_not_ready": 409, "language_unknown": 400}


def _http(error: StoryError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 404), detail={"code": error.code, "message": error.message}
    )


def story_router(service: StoryService, identity: IdentityService) -> Router:
    @get("/cases/{case_id:str}/story")
    async def case_story(
        case_id: FromPath[str],
        request: Request,
        language: FromQuery[Literal["uk", "en"]] = "uk",
    ) -> StoryResponse:
        actor = await require_actor(request, identity)
        try:
            story = await service.for_case(case_id, actor_id=actor.id, role=actor.role, language=language)
        except StoryError as error:
            raise _http(error) from error
        return story_response(story)

    @post("/story")
    async def spec_story(data: JSONBody[StoryRequest], request: Request) -> StoryResponse:
        await require_actor(request, identity)
        try:
            story = await service.for_spec(
                variable_id=data.variable_id, region_id=data.region_id, language=data.language
            )
        except StoryError as error:
            raise _http(error) from error
        return story_response(story)

    return Router(path="/api/v1", route_handlers=[case_story, spec_story])
