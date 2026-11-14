"""Read the caller from a bearer token. Public routes do not use this."""

from __future__ import annotations

from dataclasses import dataclass

from litestar import Request
from litestar.exceptions import HTTPException

from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.identity.model import IdentityError, allows


@dataclass(frozen=True)
class Actor:
    id: str
    role: str


async def require_actor(request: Request, identity: IdentityService) -> Actor:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Потрібна сесія"})
    token = header.split(" ", 1)[1].strip()
    try:
        user_id, role = await identity.read_session(token)
    except IdentityError as error:
        raise HTTPException(status_code=401, detail={"code": error.code, "message": error.message}) from error
    return Actor(id=user_id, role=role)


def require_admin(actor: Actor) -> None:
    if not allows(actor.role, "admin"):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Потрібна роль admin"})
