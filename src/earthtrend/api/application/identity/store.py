"""Ports for the identity store, the session cache, and the clock."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from earthtrend.api.domain.identity.model import ApiKey, AuditRecord, User


class IdentityStore(Protocol):
    audit: list[AuditRecord]

    async def add_user(self, user: User) -> None: ...

    async def get_by_username(self, username: str) -> User | None: ...

    async def get_by_id(self, user_id: str) -> User | None: ...

    async def insert_guest(self) -> User: ...

    async def insert_user(self, *, username: str, password_hash: str) -> User: ...

    async def issue_key(self, *, actor_id: str, owner_id: str) -> ApiKey: ...

    async def revoke_key(self, *, actor_id: str, key_id: str) -> None: ...

    async def add_review(self, *, actor_id: str, case_id: str, note: str) -> str: ...

    async def record_admin(self, *, actor_id: str, action: str, subject_id: str) -> AuditRecord: ...


class UserCache(Protocol):
    async def get(self, user_id: str) -> User | None: ...

    async def put(self, user: User) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
