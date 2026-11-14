"""Readiness probe for the database. Repositories arrive in stage B3."""

from __future__ import annotations

from typing import Protocol


class DatabaseProbe(Protocol):
    async def ping(self) -> bool: ...
