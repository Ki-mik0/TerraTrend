"""Identity HTTP routes."""

from __future__ import annotations

from litestar import Request, Router, delete, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, JSONBody

from earthtrend.api.api.identity.schemas import (
    IssueKeyRequest,
    KeyResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ReviewRequest,
    ReviewResponse,
    SessionReadResponse,
    SessionResponse,
)
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.identity.model import IdentityError


def _http(error: IdentityError) -> HTTPException:
    status = {
        "invalid_credentials": 401,
        "invalid_token": 401,
        "forbidden": 403,
        "user_not_found": 404,
        "key_not_found": 404,
        "case_not_found": 404,
        "review_not_allowed": 409,
        "username_taken": 409,
        "password_empty": 422,
        "username_invalid": 422,
        "note_empty": 422,
        "role_invalid": 422,
    }.get(error.code, 422)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def identity_router(service: IdentityService) -> Router:
    def session(token: str) -> SessionResponse:
        return SessionResponse(token=token, expires_at=service.expires_at(token))

    @post("/session")
    async def login(data: JSONBody[LoginRequest]) -> SessionResponse:
        try:
            token = await service.login(username=data.username, password=data.password)
        except IdentityError as error:
            raise _http(error) from error
        return session(token)

    @post("/session/guest")
    async def guest_session() -> SessionResponse:
        return session(await service.issue_guest())

    @post("/session/register")
    async def register(data: JSONBody[RegisterRequest]) -> SessionResponse:
        try:
            token = await service.register(username=data.username, password=data.password)
        except IdentityError as error:
            raise _http(error) from error
        return session(token)

    @post("/session/refresh")
    async def refresh_session(data: JSONBody[RefreshRequest]) -> SessionResponse:
        """Swap a live or recently expired token for a new one, so a session survives without signing in again."""
        try:
            token = await service.refresh(data.token)
        except IdentityError as error:
            raise _http(error) from error
        return session(token)

    @get("/session")
    async def read_session(request: Request) -> SessionReadResponse:
        actor = await require_actor(request, service)
        return SessionReadResponse(user_id=actor.id, role=actor.role)

    @post("/admin/api-keys")
    async def issue_key(data: JSONBody[IssueKeyRequest], request: Request) -> KeyResponse:
        actor = await require_actor(request, service)
        try:
            key = await service.issue_key(actor_id=actor.id, role=actor.role, owner_id=data.owner_id)
        except IdentityError as error:
            raise _http(error) from error
        return KeyResponse(id=key.id, secret=key.secret, revoked=key.revoked)

    @delete("/admin/api-keys/{key_id:str}", status_code=204)
    async def revoke_key(key_id: FromPath[str], request: Request) -> None:
        actor = await require_actor(request, service)
        try:
            await service.revoke_key(actor_id=actor.id, role=actor.role, key_id=key_id)
        except IdentityError as error:
            raise _http(error) from error

    @post("/admin/ai-reviews")
    async def review(data: JSONBody[ReviewRequest], request: Request) -> ReviewResponse:
        actor = await require_actor(request, service)
        try:
            created = await service.review(
                actor_id=actor.id,
                role=actor.role,
                case_id=data.case_id,
                note=data.note,
            )
        except IdentityError as error:
            raise _http(error) from error
        return ReviewResponse(id=created.id, case_id=created.case_id, actor_id=created.actor_id, note=created.note)

    return Router(
        path="/api/v1",
        route_handlers=[login, guest_session, register, refresh_session, read_session, issue_key, revoke_key, review],
    )
