"""StoryFacts from a real case, or from a fresh analysis of a bare spec. No invented values."""

from __future__ import annotations

from typing import Any, Protocol

from earthtrend.api.application.catalog.service import CatalogService
from earthtrend.api.domain.cases.model import (
    AnalysisProduct,
    Case,
    CaseError,
    CaseSpec,
    EvidenceProtocol,
    SeriesArtifact,
    Verdict,
)
from earthtrend.api.domain.catalog.model import CatalogError
from earthtrend.api.domain.story.model import StoryError, StoryFacts
from earthtrend.api.infrastructure.story.knowledge import papers_for, pattern_for, related_for

PERIOD_START = "2000-01"
PERIOD_END = "2025-12"


class AnalysisPort(Protocol):
    async def run(self, spec: CaseSpec) -> AnalysisProduct: ...


def _caveats(series: SeriesArtifact, warnings: list[str] | None = None) -> tuple[str, ...]:
    found = list(warnings or [])
    if series.split.split_flag:
        found.append("split_region")
    if series.jackknife.influential_year is not None:
        found.append("influential_year")
    return tuple(dict.fromkeys(found))


def build_facts(
    *,
    variable_id: str,
    region_id: str,
    verdict: Verdict,
    evidence: EvidenceProtocol | None,
    series: SeriesArtifact,
    warnings: list[str] | None = None,
    names: tuple[str, str] = ("", ""),
    versions: dict[str, str] | None = None,
) -> StoryFacts:
    pattern = pattern_for(variable_id, verdict.direction)
    versions = {"ruleset": verdict.ruleset, **{key: value for key, value in (versions or {}).items() if value}}
    return StoryFacts(
        variable_id=variable_id,
        region_id=region_id,
        direction=verdict.direction,
        slope_decade=series.slope_decade,
        pattern=pattern,
        related=related_for(variable_id),
        patterns=(pattern,),
        alibi=None if evidence is None else (evidence.alibi.b_raw, evidence.alibi.b_adjusted),
        witnesses=None if evidence is None else (evidence.witnesses.confirmed, evidence.witnesses.total),
        papers=papers_for(variable_id),
        caveats=_caveats(series, warnings),
        versions=versions,
        variable_name=names[0],
        region_name=names[1],
    )


class CaseFacts:
    """Facts follow the case: its variable, verdict direction, slope, alibi and witnesses."""

    def __init__(self, analysis: AnalysisPort, catalog: CatalogService | None = None) -> None:
        self._analysis = analysis
        self._catalog = catalog

    async def for_case(self, case: Case) -> StoryFacts:
        if case.verdict is None or case.series is None:
            raise ValueError(f"case {case.id} has no computed facts")
        facts = build_facts(
            variable_id=case.spec.variable_id,
            region_id=case.spec.region_id,
            verdict=case.verdict,
            evidence=case.evidence,
            series=case.series,
            warnings=case.warnings,
            names=await self._names(case.spec.variable_id, case.spec.region_id),
            versions=_versions(case.catalog_version, case.datasets_version, case.algorithm_version),
        )
        if case.source_series is None:
            return facts
        from earthtrend.api.infrastructure.analytics_bridge import facts_from_story, run_blocking

        lens = await run_blocking(facts_from_story, case.source_series)
        from earthtrend.api.domain.story.model import RelatedVariable

        return StoryFacts(
            variable_id=facts.variable_id,
            region_id=facts.region_id,
            direction=lens["direction"] if lens["direction"] != "none" else facts.direction,
            slope_decade=lens["slope_decade"],
            pattern=lens["patterns"][0] if lens["patterns"] else facts.pattern,
            related=tuple(RelatedVariable(**item) for item in lens["related"]) or facts.related,
            patterns=tuple(lens["patterns"]) or facts.patterns,
            alibi=facts.alibi,
            witnesses=facts.witnesses,
            papers=facts.papers,
            caveats=tuple(lens["caveats"]) or facts.caveats,
            versions=facts.versions,
            variable_name=facts.variable_name,
            region_name=facts.region_name,
        )

    async def for_spec(self, *, variable_id: str, region_id: str) -> StoryFacts:
        try:
            product = await self._analysis.run(
                CaseSpec(variable_id=variable_id, region_id=region_id, period_start=PERIOD_START, period_end=PERIOD_END)
            )
        except CaseError as error:
            raise StoryError("data_not_ready") from error
        return build_facts(
            variable_id=variable_id,
            region_id=region_id,
            verdict=product.verdict,
            evidence=product.evidence,
            series=product.series,
            names=await self._names(variable_id, region_id),
            versions=_versions(product.catalog_version, product.datasets_version, product.algorithm_version),
        )

    async def _names(self, variable_id: str, region_id: str) -> tuple[str, str]:
        if self._catalog is None:
            return "", ""
        return await _name(self._catalog.get_variable, variable_id), await _name(self._catalog.get_region, region_id)


def _versions(catalog: str, datasets: str, algorithm: str) -> dict[str, str]:
    return {"catalog": catalog, "datasets": datasets, "algorithm": algorithm}


async def _name(getter: Any, item_id: str) -> str:
    try:
        return (await getter(item_id)).name
    except CatalogError:
        return ""


class CatalogStoryCheck:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def has_variable(self, variable_id: str) -> bool:
        return bool(await _name(self._catalog.get_variable, variable_id))

    async def has_region(self, region_id: str) -> bool:
        return bool(await _name(self._catalog.get_region, region_id))
