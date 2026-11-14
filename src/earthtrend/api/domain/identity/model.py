"""Identity: a user, an API key inside it, an audit log, and a separate AI review."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

ROLES = ("guest", "user", "teacher", "admin")
_RANK = {role: index for index, role in enumerate(ROLES)}
_ACTIONS = {
    "view_demos": "guest",
    "open_case": "guest",
    "view_radar": "guest",
    "save_case": "user",
    "write_note": "user",
    "export": "user",
    "assistant": "user",
    "teach": "teacher",
    "admin": "admin",
}


class IdentityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def allows(role: str, action: str) -> bool:
    if role not in _RANK or action not in _ACTIONS:
        return False
    return _RANK[role] >= _RANK[_ACTIONS[action]]


@dataclass
class ApiKey:
    id: str
    secret: str
    revoked: bool = False


@dataclass
class User:
    id: str
    username: str
    role: str
    password_hash: str
    keys: list[ApiKey] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.role not in _RANK:
            raise IdentityError("role_invalid", "Невідома роль")


@dataclass
class AuditRecord:
    id: str
    actor_id: str
    action: str
    subject_id: str
    created_at: datetime | None = None


@dataclass
class AiReview:
    id: str
    case_id: str
    actor_id: str
    note: str
