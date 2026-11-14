"""Memory journal keeps one saved case when the same case is remembered twice."""

from earthtrend.api.application.journal.service import JournalService
from earthtrend.api.domain.cases.model import Case, CaseSpec
from earthtrend.api.domain.journal.model import SavedCase
from earthtrend.api.infrastructure.journal.memory import MemoryJournalStore


class _Cases:
    def __init__(self, case: Case) -> None:
        self.case = case

    async def get(self, case_id: str) -> Case | None:
        return self.case if self.case.id == case_id else None


async def test_remembering_the_same_case_twice_keeps_one_reference() -> None:
    case = Case(
        id="case_1",
        owner_id="u1",
        role="user",
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"),
    )
    service = JournalService(cases=_Cases(case), store=MemoryJournalStore())
    await service.remember(owner_id="u1", case_id="case_1", ephemeral=False)
    await service.remember(owner_id="u1", case_id="case_1", ephemeral=False)
    assert await service.list_cases(actor_id="u1") == [SavedCase(owner_id="u1", case_id="case_1")]
