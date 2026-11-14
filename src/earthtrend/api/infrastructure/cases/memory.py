"""In-memory case store, analysis, and job queue."""

from __future__ import annotations

from earthtrend.api.domain.cases.model import AnalysisProduct, Case, CaseSpec, assert_storable
from earthtrend.api.infrastructure.cases.product import (
    ALGORITHM_VERSION,
    CATALOG_VERSION,
    DATASETS_VERSION,
    product_for,
)


class MemoryCaseStore:
    def __init__(self) -> None:
        self.cases: dict[str, Case] = {}
        self._seq = 0

    async def next_id(self) -> str:
        self._seq += 1
        return f"case_{self._seq}"

    async def save(self, case: Case) -> None:
        assert_storable(case)
        self.cases[case.id] = case

    async def get(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)

    async def delete(self, case_id: str) -> None:
        self.cases.pop(case_id, None)

    async def list_owned(self, owner_id: str) -> list[Case]:
        return [case for case in self.cases.values() if case.owner_id == owner_id]


class MemoryAnalysis:
    def __init__(self) -> None:
        self.catalog_version = CATALOG_VERSION
        self.datasets_version = DATASETS_VERSION
        self.algorithm_version = ALGORITHM_VERSION
        self.calls = 0

    async def run(self, spec: CaseSpec) -> AnalysisProduct:
        self.calls += 1
        return product_for(
            spec,
            catalog_version=self.catalog_version,
            datasets_version=self.datasets_version,
            algorithm_version=self.algorithm_version,
        )


class MemoryJobs:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def enqueue(self, case_id: str) -> str:
        job_id = f"job_{case_id}"
        self.ids.append(job_id)
        return job_id


class MemoryAssignments:
    def __init__(self, linked: set[str] | None = None) -> None:
        self.linked = linked or set()

    async def is_linked(self, case_id: str) -> bool:
        return case_id in self.linked

    async def link(self, case_id: str) -> None:
        self.linked.add(case_id)
