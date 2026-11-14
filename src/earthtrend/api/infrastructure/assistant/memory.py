"""In-memory stand-ins: neighbors, exchange history, plan cache, and rate limiter."""

from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from earthtrend.api.domain.assistant.exchange import AssistantExchange, ToolStep

CASE_ID = "case_mem_1"
VARIABLES = {
    "gldas_sm": {"id": "gldas_sm", "name": "Soil moisture"},
    "merra2_t2m": {"id": "merra2_t2m", "name": "Air temperature"},
}
REGIONS = {
    "ukraine_south": {"id": "ukraine_south", "name": "Ukraine south"},
}
CASE_FACTS = {
    "case_id": CASE_ID,
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "slope_decade": 0.42,
    "p_mk": 0.002,
    "verdict": "strong",
}


def _match(items: dict[str, dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.casefold()
    found = [item for item in items.values() if needle in item["id"].casefold() or needle in item["name"].casefold()]
    return found or list(items.values())


class MemoryCatalog:
    async def ids(self) -> set[str]:
        return set(VARIABLES)

    async def region_ids(self) -> set[str]:
        return set(REGIONS)

    async def search_variables(self, query: str) -> list[dict[str, Any]]:
        return _match(VARIABLES, query)

    async def get_variable(self, variable_id: str) -> dict[str, Any] | None:
        return VARIABLES.get(variable_id)

    async def search_regions(self, query: str) -> list[dict[str, Any]]:
        return _match(REGIONS, query)


class MemoryCases:
    async def analyze(
        self, *, variable_id: str, region_id: str, season: str | None, owner_id: str = "", role: str = "guest"
    ) -> dict[str, Any]:
        del owner_id, role
        return {**CASE_FACTS, "variable_id": variable_id, "region_id": region_id, "season": season}

    async def compare(self, case_ids: list[str], *, owner_id: str = "", role: str = "guest") -> dict[str, Any]:
        del owner_id, role
        return {"cases": [{**CASE_FACTS, "case_id": case_id} for case_id in case_ids]}


class MemoryEvidence:
    async def get(self, case_id: str, *, owner_id: str = "", role: str = "guest") -> dict[str, Any]:
        del owner_id, role
        return {"case_id": case_id, "p_mk": CASE_FACTS["p_mk"], "slope_decade": CASE_FACTS["slope_decade"]}


class MemoryStory:
    async def get(self, case_id: str, *, owner_id: str = "", role: str = "guest") -> dict[str, Any]:
        del owner_id, role
        return {"case_id": case_id, "pattern": "drying"}


class MemoryProfile:
    async def get(self, case_id: str, *, owner_id: str = "", role: str = "guest") -> dict[str, Any]:
        del owner_id, role
        return {"case_id": case_id, "changepoints": [], "influential_year": None}


class MemoryUrban:
    async def get(self, case_id: str, *, owner_id: str = "", role: str = "guest") -> dict[str, Any]:
        del owner_id, role
        return {"case_id": case_id, "zones": []}


class MemoryRadar:
    async def feed(self) -> list[dict[str, Any]]:
        return [{"id": "radar_mem_1", "variable_id": "gldas_sm", "case_id": CASE_ID}]


class MemoryNotes:
    def __init__(self) -> None:
        self.notes: list[dict[str, Any]] = []

    async def write(
        self, *, question: str, plan: list[ToolStep], case_ids: list[str], author_id: str = "", role: str = "guest"
    ) -> None:
        del role
        self.notes.append(
            {
                "question": question,
                "author_id": author_id,
                "plan": [{"tool": step.tool, "input": step.input} for step in plan],
                "case_ids": list(case_ids),
            }
        )


class MemoryExchangeRepository:
    def __init__(self) -> None:
        self.items: dict[str, AssistantExchange] = {}

    async def save(self, exchange: AssistantExchange) -> None:
        self.items[exchange.id] = deepcopy(exchange)

    async def get(self, exchange_id: str, *, owner_id: str) -> AssistantExchange | None:
        found = self.items.get(exchange_id)
        if found is None or found.owner_id != owner_id:
            return None
        return deepcopy(found)

    async def list(self, *, owner_id: str, limit: int) -> list[AssistantExchange]:
        owned = [item for item in self.items.values() if item.owner_id == owner_id]
        owned.sort(key=lambda item: (item.created_at is None, item.created_at), reverse=True)
        return [deepcopy(item) for item in owned[:limit]]


class MemoryPlanCache:
    def __init__(self) -> None:
        self.items: dict[str, list[ToolStep]] = {}

    async def get(self, key: str) -> list[ToolStep] | None:
        found = self.items.get(key)
        return None if found is None else list(found)

    async def put(self, key: str, steps: list[ToolStep]) -> None:
        self.items[key] = list(steps)


class MemoryRateLimiter:
    """Fixed one-minute window per actor, like the Redis limiter."""

    def __init__(self, limit: int = 20, window_seconds: int = 60, now: Callable[[], float] = time.time) -> None:
        self._limit = limit
        self._window = window_seconds
        self._now = now
        self._counts: dict[tuple[str, int], int] = {}

    async def allow(self, actor_id: str) -> bool:
        bucket = (actor_id, int(self._now()) // self._window)
        self._counts = {key: value for key, value in self._counts.items() if key[1] == bucket[1]}
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        return self._counts[bucket] <= self._limit
