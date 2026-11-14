"""Assistant tools that call the live domain services, so the same access and cache rules apply."""

from __future__ import annotations

from typing import Any

from earthtrend.api.application.cases.service import CaseService
from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.application.journal.service import JournalService
from earthtrend.api.application.radar.service import RadarService
from earthtrend.api.application.story.service import StoryService
from earthtrend.api.domain.assistant.exchange import ToolStep
from earthtrend.api.domain.cases.model import Case, CaseError, CaseSpec
from earthtrend.api.domain.catalog.model import CatalogError
from earthtrend.api.domain.journal.model import JournalError
from earthtrend.api.domain.story.model import StoryError

PERIOD_START = "2000-01"
PERIOD_END = "2025-12"


def case_summary(case: Case) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "variable_id": case.spec.variable_id,
        "region_id": case.spec.region_id,
        "season": case.spec.season,
        "status": case.status,
        "verdict": None if case.verdict is None else case.verdict.code,
        "direction": None if case.verdict is None else case.verdict.direction,
        "slope_decade": None if case.series is None else case.series.slope_decade,
        "warnings": list(case.warnings),
    }


class LiveCatalog:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def ids(self) -> set[str]:
        return {item.id for item in await self._catalog.list_variables()}

    async def region_ids(self) -> set[str]:
        return {item.id for item in await self._catalog.list_regions()}

    async def search_variables(self, query: str) -> list[dict[str, Any]]:
        return [{"id": item.id, "name": item.name} for item in await self._catalog.list_variables(query)]

    async def get_variable(self, variable_id: str) -> dict[str, Any] | None:
        try:
            item = await self._catalog.get_variable(variable_id)
        except CatalogError:
            return None
        return {"id": item.id, "name": item.name}

    async def search_regions(self, query: str) -> list[dict[str, Any]]:
        return [{"id": item.id, "name": item.name} for item in await self._catalog.list_regions(query)]


class LiveCases:
    def __init__(self, cases: CaseService) -> None:
        self._cases = cases

    async def analyze(
        self, *, variable_id: str, region_id: str, season: str | None, owner_id: str, role: str
    ) -> dict[str, Any]:
        try:
            case = await self._cases.create(
                spec=CaseSpec(
                    variable_id=variable_id,
                    region_id=region_id,
                    period_start=PERIOD_START,
                    period_end=PERIOD_END,
                    season=season,
                ),
                owner_id=owner_id,
                role=role,
            )
        except CaseError as error:
            return {"variable_id": variable_id, "region_id": region_id, "error": error.code}
        return case_summary(case)

    async def compare(self, case_ids: list[str], *, owner_id: str, role: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for case_id in case_ids:
            try:
                rows.append(case_summary(await self._cases.get(case_id, actor_id=owner_id, role=role)))
            except CaseError as error:
                rows.append({"case_id": case_id, "error": error.code})
        return {"cases": rows}


class LiveEvidence:
    def __init__(self, cases: CaseService) -> None:
        self._cases = cases

    async def get(self, case_id: str, *, owner_id: str, role: str) -> dict[str, Any]:
        try:
            evidence = await self._cases.evidence(case_id, actor_id=owner_id, role=role)
        except CaseError as error:
            return {"case_id": case_id, "error": error.code}
        return {
            "case_id": case_id,
            "version": evidence.version,
            "verdict_code": evidence.verdict_code,
            "witnesses_confirmed": evidence.witnesses.confirmed,
            "witnesses_total": evidence.witnesses.total,
            "same_sign_share": evidence.triangle.same_sign_share,
            "alibi_b_raw": evidence.alibi.b_raw,
            "alibi_b_adjusted": evidence.alibi.b_adjusted,
        }


class LiveProfile:
    """Shape of the series: changepoints, the influential year, and a split region."""

    def __init__(self, cases: CaseService) -> None:
        self._cases = cases

    async def get(self, case_id: str, *, owner_id: str, role: str) -> dict[str, Any]:
        try:
            case = await self._cases.get(case_id, actor_id=owner_id, role=role)
        except CaseError as error:
            return {"case_id": case_id, "error": error.code}
        if case.series is None:
            return {"case_id": case_id, "error": "series_not_ready"}
        series = case.series
        return {
            "case_id": case_id,
            "slope_decade": series.slope_decade,
            "influential_year": series.jackknife.influential_year,
            "split_region": series.split.split_flag,
            "changepoints": [{"year": item.year, "probability": item.probability} for item in series.changepoints],
        }


class LiveUrban:
    """Zones of the region with their own sign and slope, already computed by analytics."""

    def __init__(self, cases: CaseService) -> None:
        self._cases = cases

    async def get(self, case_id: str, *, owner_id: str, role: str) -> dict[str, Any]:
        try:
            case = await self._cases.get(case_id, actor_id=owner_id, role=role)
        except CaseError as error:
            return {"case_id": case_id, "error": error.code}
        if case.series is None:
            return {"case_id": case_id, "error": "series_not_ready"}
        return {
            "case_id": case_id,
            "zones": [{"sign": zone.sign, "slope_decade": zone.slope_decade} for zone in case.series.zones],
        }


class LiveStory:
    def __init__(self, stories: StoryService) -> None:
        self._stories = stories

    async def get(self, case_id: str, *, owner_id: str, role: str) -> dict[str, Any]:
        try:
            story = await self._stories.for_case(case_id, actor_id=owner_id, role=role)
        except StoryError as error:
            return {"case_id": case_id, "error": error.code}
        return {
            "case_id": case_id,
            "text": story.text,
            "pattern": story.facts.pattern,
            "direction": story.facts.direction,
            "related": [item.variable_id for item in story.facts.related],
            "caveats": list(story.caveats),
        }


class LiveRadar:
    def __init__(self, radar: RadarService) -> None:
        self._radar = radar

    async def feed(self) -> list[dict[str, Any]]:
        items = await self._radar.feed(feed="strongest")
        return [
            {"id": item.id, "variable_id": item.variable_id, "region_id": item.region_id, "case_id": item.case_id}
            for item in items
        ]


class LiveNotes:
    def __init__(self, journal: JournalService) -> None:
        self._journal = journal

    async def write(
        self, *, question: str, plan: list[ToolStep], case_ids: list[str], author_id: str, role: str
    ) -> None:
        if not case_ids:
            return
        tools = " → ".join(step.tool for step in plan)
        text = f"{question}\n\nПлан: {tools}\nСправи: {', '.join(case_ids)}"
        try:
            await self._journal.add_note(author_id=author_id, role=role, case_id=case_ids[0], text=text)
        except JournalError:
            return
