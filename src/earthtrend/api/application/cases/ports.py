"""Ports for analysis, the job queue, and case storage."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.cases.model import AnalysisProduct, Case, CaseSpec


class CaseStore(Protocol):
    async def next_id(self) -> str: ...

    async def save(self, case: Case) -> None: ...

    async def get(self, case_id: str) -> Case | None: ...

    async def delete(self, case_id: str) -> None: ...

    async def list_owned(self, owner_id: str) -> list[Case]: ...


class AnalysisPort(Protocol):
    catalog_version: str
    datasets_version: str
    algorithm_version: str

    async def run(self, spec: CaseSpec) -> AnalysisProduct: ...


class JobPort(Protocol):
    async def enqueue(self, case_id: str) -> str: ...


class AssignmentPort(Protocol):
    async def is_linked(self, case_id: str) -> bool: ...


class FeedbackPort(Protocol):
    async def record(self, *, region_id: str, case_id: str, verdict_code: str) -> None: ...


class RememberPort(Protocol):
    async def remember(self, *, owner_id: str, case_id: str, ephemeral: bool) -> None: ...


class AchievementPort(Protocol):
    """Told about every finished case, so education can award badges inside the application layer."""

    async def case_completed(self, case: Case) -> object: ...
