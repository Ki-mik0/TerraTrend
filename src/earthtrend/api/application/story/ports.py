"""Ports Story Lens uses: facts from analytics, a narrator, the catalog, and case lookup."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.story.model import Draft, StoryFacts


class FactsPort(Protocol):
    async def for_case(self, case: Case) -> StoryFacts: ...

    async def for_spec(self, *, variable_id: str, region_id: str) -> StoryFacts: ...


class NarratorPort(Protocol):
    async def write(self, *, language: str, facts: StoryFacts) -> Draft: ...


class CatalogCheck(Protocol):
    async def has_variable(self, variable_id: str) -> bool: ...

    async def has_region(self, region_id: str) -> bool: ...


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...
