"""Queue an export and hand back the file built from the stored case."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.exports.model import ExportError, ExportRecord, require_format
from earthtrend.api.infrastructure.exports.render import render


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class ExportService:
    def __init__(self, *, cases: CaseLookup) -> None:
        self._cases = cases
        self.records: dict[str, ExportRecord] = {}
        self._seq = 0

    async def create(self, *, case_id: str, fmt: str, actor_id: str) -> ExportRecord:
        require_format(fmt)
        case = await self._visible_case(case_id, actor_id)
        if case.status != "completed" or case.series is None or case.verdict is None or case.evidence is None:
            raise ExportError("case_not_ready", "Експорт потребує завершеної справи")
        self._seq += 1
        record = ExportRecord(id=f"exp_{self._seq}", case_id=case.id, owner_id=case.owner_id, format=fmt)
        self.records[record.id] = record
        record.mark_ready(render(case, fmt))
        return record

    async def get(self, export_id: str, *, actor_id: str) -> ExportRecord:
        record = self.records.get(export_id)
        if record is None or not record.visible_to(actor_id):
            raise ExportError("export_not_found", "Експорт не знайдено")
        return record

    async def download(self, export_id: str, *, actor_id: str) -> bytes:
        record = await self.get(export_id, actor_id=actor_id)
        if record.status != "ready" or record.body is None:
            raise ExportError("export_not_ready", "Файл ще не зібрано")
        return record.body

    async def _visible_case(self, case_id: str, actor_id: str) -> Case:
        case = await self._cases.get(case_id)
        if case is None or case.owner_id != actor_id:
            raise ExportError("case_not_found", "Справу не знайдено")
        return case
