"""Ports the assistant uses. Neighboring domains, storage and the model are behind these interfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from earthtrend.api.domain.assistant.exchange import AssistantExchange, ToolStep


class CatalogPort(Protocol):
    async def ids(self) -> set[str]: ...

    async def region_ids(self) -> set[str]: ...

    async def search_variables(self, query: str) -> list[dict[str, Any]]: ...

    async def get_variable(self, variable_id: str) -> dict[str, Any] | None: ...

    async def search_regions(self, query: str) -> list[dict[str, Any]]: ...


class CasePort(Protocol):
    async def analyze(
        self, *, variable_id: str, region_id: str, season: str | None, owner_id: str, role: str
    ) -> dict[str, Any]: ...

    async def compare(self, case_ids: list[str], *, owner_id: str, role: str) -> dict[str, Any]: ...


class CaseFactsPort(Protocol):
    """Evidence, vertical profile, urban contrast, and story facts of one case."""

    async def get(self, case_id: str, *, owner_id: str, role: str) -> dict[str, Any]: ...


class RadarPort(Protocol):
    async def feed(self) -> list[dict[str, Any]]: ...


class NotePort(Protocol):
    async def write(
        self, *, question: str, plan: list[ToolStep], case_ids: list[str], author_id: str, role: str
    ) -> None: ...


class NarratorPort(Protocol):
    async def plan(
        self, *, question: str, language: str, mode: str, catalog_ids: set[str]
    ) -> list[ToolStep]: ...

    async def answer(
        self, *, question: str, language: str, mode: str, facts: list[dict[str, Any]], case_ids: list[str]
    ) -> str: ...


class ExchangeRepository(Protocol):
    async def save(self, exchange: AssistantExchange) -> None: ...

    async def get(self, exchange_id: str, *, owner_id: str) -> AssistantExchange | None: ...

    async def list(self, *, owner_id: str, limit: int) -> list[AssistantExchange]: ...


class PlanCache(Protocol):
    async def get(self, key: str) -> list[ToolStep] | None: ...

    async def put(self, key: str, steps: list[ToolStep]) -> None: ...


class RateLimiter(Protocol):
    async def allow(self, actor_id: str) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
