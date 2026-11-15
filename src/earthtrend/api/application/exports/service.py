"""Queue an export and hand back the file built from the stored case."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.exports.model import ExportError, ExportRecord, require_format
from earthtrend.api.infrastructure.exports.render import filename, render
from earthtrend.api.infrastructure.exports.report import Names, build_report


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class CatalogLookup(Protocol):
    async def get_variable(self, variable_id: str) -> object: ...

    async def get_region(self, region_id: str) -> object: ...


class ExportService:
    def __init__(self, *, cases: CaseLookup, catalog: CatalogLookup | None = None) -> None:
        self._cases = cases
        self._catalog = catalog
        self.records: dict[str, ExportRecord] = {}
        self._seq = 0

    async def create(self, *, case_id: str, fmt: str, actor_id: str, language: str | None = None) -> ExportRecord:
        require_format(fmt)
        case = await self._visible_case(case_id, actor_id)
        if case.status != "completed" or case.series is None or case.verdict is None or case.evidence is None:
            raise ExportError("case_not_ready", "Експорт потребує завершеної справи")
        self._seq += 1
        names = await self._names(case, language or case.spec.language)
        record = ExportRecord(id=f"exp_{self._seq}", case_id=case.id, owner_id=case.owner_id, format=fmt)
        self.records[record.id] = record
        record.filename = filename(build_report(case, names, language), fmt)
        record.mark_ready(render(case, fmt, names, language))
        return record

    async def _names(self, case: Case, language: str) -> Names:
        """Human names, units, dataset DOI and region box from the catalog; ids when there is no catalog."""
        variable, region = case.spec.variable_id, case.spec.region_id
        units, doi, bbox = "", "", None
        if self._catalog is not None:
            try:
                passport = await self._catalog.get_variable(variable)
                variable = (getattr(passport, "name_uk", "") if language != "en" else "") or getattr(passport, "name", variable)
                units = getattr(passport, "units", "") or ""
                doi = getattr(passport, "doi", "") or ""
            except Exception:  # an unknown id keeps the id; the export still works
                pass
            try:
                place = await self._catalog.get_region(region)
                region = (getattr(place, "name_uk", "") if language != "en" else "") or getattr(place, "name", region)
                bbox = tuple(getattr(place, "bbox", ())) or None
            except Exception:
                pass
        return Names(variable=variable, region=region, units=units, doi=doi, bbox=bbox)

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
