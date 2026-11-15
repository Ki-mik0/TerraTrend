"""Live adapters call the real neighbor services with the caller's rights."""

from __future__ import annotations

from earthtrend.api.domain.assistant.exchange import ToolStep
from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.infrastructure.assistant.live import (
    LiveCases,
    LiveCatalog,
    LiveEvidence,
    LiveNotes,
    LiveProfile,
    LiveRadar,
    LiveStory,
    LiveUrban,
)
from earthtrend.api.infrastructure.assistant.narrator import FallbackNarrator, TemplateNarrator
from earthtrend.api.infrastructure.assistant.wiring import Neighbors, build_assistant_service
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.journal.wiring import build_journal_service
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.radar.memory import seed_radar
from earthtrend.api.infrastructure.story.narrators import ChainNarrator
from earthtrend.api.infrastructure.story.wiring import build_story_service


def _world():
    store = MemoryCaseStore()
    journal = build_journal_service(store)
    cases = build_case_service(store=store, remember=journal)
    stories = build_story_service(cases=store, narrator=ChainNarrator())
    return store, journal, cases, stories


async def test_live_catalog_and_radar() -> None:
    catalog = LiveCatalog(seed_catalog())
    assert {"gldas_sm"} <= await catalog.ids()
    assert "ukraine_south" in await catalog.region_ids()
    assert await catalog.search_variables("Soil")
    assert (await catalog.get_variable("gldas_sm"))["id"] == "gldas_sm"
    assert await catalog.get_variable("nope") is None
    assert await catalog.search_regions("ukraine")
    feed = await LiveRadar(seed_radar()).feed()
    assert feed and {"id", "variable_id", "region_id", "open_with"} <= set(feed[0])
    assert "case_id" not in feed[0]  # a radar card is not a case; a fake id would end in case_not_found


async def test_live_case_tools_respect_owner() -> None:
    _, _, cases, stories = _world()
    live = LiveCases(cases)
    created = await live.analyze(variable_id="gldas_sm", region_id="ukraine_south", season="JJA", owner_id="u1", role="user")
    case_id = created["case_id"]
    assert created["verdict"] and created["slope_decade"] is not None

    evidence = await LiveEvidence(cases).get(case_id, owner_id="u1", role="user")
    assert evidence["verdict_code"] == created["verdict"] and "witnesses_total" in evidence
    profile = await LiveProfile(cases).get(case_id, owner_id="u1", role="user")
    assert "changepoints" in profile and "influential_year" in profile
    urban = await LiveUrban(cases).get(case_id, owner_id="u1", role="user")
    assert isinstance(urban["zones"], list)
    story = await LiveStory(stories).get(case_id, owner_id="u1", role="user")
    assert story["text"] and story["pattern"] == "drying"
    assert "merra2_t2m" in story["related"] and "correlation_not_causation" in story["caveats"]
    compared = await live.compare([case_id, "missing"], owner_id="u1", role="user")
    assert compared["cases"][0]["case_id"] == case_id
    assert compared["cases"][1] == {"case_id": "missing", "error": "case_not_found"}

    for adapter in (LiveEvidence(cases), LiveProfile(cases), LiveUrban(cases), LiveStory(stories)):
        assert (await adapter.get(case_id, owner_id="intruder", role="user"))["error"] == "case_not_found"


async def test_live_tools_report_cases_without_series() -> None:
    _, _, cases, _ = _world()
    queued = await cases.create(
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12", heavy=True), owner_id="u1", role="user"
    )
    assert (await LiveProfile(cases).get(queued.id, owner_id="u1", role="user"))["error"] == "series_not_ready"
    assert (await LiveUrban(cases).get(queued.id, owner_id="u1", role="user"))["error"] == "series_not_ready"
    assert (await LiveEvidence(cases).get(queued.id, owner_id="u1", role="user"))["error"] == "evidence_not_ready"


async def test_live_analyze_turns_case_errors_into_facts() -> None:
    class Failing:
        async def create(self, **kwargs):
            from earthtrend.api.domain.cases.model import CaseError

            raise CaseError("period_too_short", "x")

    result = await LiveCases(Failing()).analyze(
        variable_id="gldas_sm", region_id="r", season=None, owner_id="u1", role="user"
    )
    assert result == {"variable_id": "gldas_sm", "region_id": "r", "error": "period_too_short"}


async def test_live_notes_write_plan_and_cases_and_ignore_journal_errors() -> None:
    _, journal, cases, _ = _world()
    case = await cases.create(spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"), owner_id="u1", role="user")
    notes = LiveNotes(journal)
    plan = [ToolStep("analyze_case", "", {}), ToolStep("get_story", "", {})]
    await notes.write(question="Чи сохне?", plan=plan, case_ids=[case.id], author_id="u1", role="user")
    saved, _ = await journal.list_journal(actor_id="u1")
    assert "analyze_case → get_story" in saved[0].text and case.id in saved[0].text

    await notes.write(question="q", plan=plan, case_ids=[], author_id="u1", role="user")
    await notes.write(question="q", plan=plan, case_ids=["missing"], author_id="u1", role="user")
    assert len((await journal.list_journal(actor_id="u1"))[0]) == 1


async def test_assistant_on_live_neighbors_writes_journal() -> None:
    _, journal, cases, stories = _world()
    catalog = seed_catalog()
    service = build_assistant_service(
        neighbors=Neighbors(
            catalog=LiveCatalog(catalog),
            cases=LiveCases(cases),
            evidence=LiveEvidence(cases),
            story=LiveStory(stories),
            profile=LiveProfile(cases),
            urban=LiveUrban(cases),
            radar=LiveRadar(seed_radar()),
            notes=LiveNotes(journal),
        ),
        narrator=FallbackNarrator(TemplateNarrator(), None),
    )
    exchange = await service.ask(question="Чи сохне ґрунт влітку?", language="uk", role="user", owner_id="u1")
    assert exchange.status == "answered" and exchange.case_ids
    assert exchange.citations[0]["case_id"] == exchange.case_ids[0]
    notes, _ = await journal.list_journal(actor_id="u1")
    assert notes and notes[0].case_id == exchange.case_ids[0]
