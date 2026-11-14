"""Create, read, list, delete a case and return its stored evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from earthtrend.api.application.cases.ports import (
    AchievementPort,
    AnalysisPort,
    AssignmentPort,
    CaseStore,
    FeedbackPort,
    JobPort,
    RememberPort,
)
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.domain.cases.codec import cache_key, dump_product, load_product
from earthtrend.api.domain.cases.model import (
    AiOpinion,
    AnalysisProduct,
    Case,
    CaseError,
    CaseSpec,
    UrbanContrast,
    VerticalProfile,
    assert_storable,
    require_compare_count,
    require_period,
)
from earthtrend.api.domain.catalog.model import CatalogError

PRODUCT_TTL = 3600


class CatalogLookup(Protocol):
    async def get_variable(self, variable_id: str) -> object: ...

    async def get_region(self, region_id: str) -> object: ...


class CaseService:
    def __init__(
        self,
        *,
        store: CaseStore,
        analysis: AnalysisPort,
        jobs: JobPort,
        assignments: AssignmentPort,
        ids: Callable[[], str] | None = None,
        feedback: FeedbackPort | None = None,
        remember: RememberPort | None = None,
        achievements: AchievementPort | None = None,
        catalog: CatalogLookup | None = None,
        cache: CachePort | None = None,
    ) -> None:
        self._store = store
        self._analysis = analysis
        self._jobs = jobs
        self._assignments = assignments
        self._ids = ids
        self._feedback = feedback
        self._remember = remember
        self._achievements = achievements
        self._catalog = catalog
        self._cache = cache
        self.finish_queued = _QueuedCases(self)

    async def create(
        self,
        *,
        spec: CaseSpec,
        owner_id: str,
        role: str,
        series: dict | None = None,
        profile_levels: dict | None = None,
        urban_cube: dict | None = None,
    ) -> Case:
        await self._known(spec)
        require_period(spec.period_start, spec.period_end)
        case_id = self._ids() if self._ids else await self._store.next_id()
        case = Case(
            id=case_id,
            owner_id=owner_id,
            role=role,
            spec=spec,
            ephemeral=role == "guest",
        )
        if spec.heavy:
            case.queue(await self._jobs.enqueue(case.id))
        else:
            if series is not None:
                product = await self._from_analytics(series, profile_levels, urban_cube)
                case.source_series = series
            else:
                product = await self._load_product(spec)
            case.complete(
                verdict=product.verdict,
                evidence=product.evidence,
                series=product.series,
                ai_opinion=AiOpinion(predicted_class="linear", confidence="medium"),
                profile=product.profile,
                urban=product.urban,
                catalog_version=product.catalog_version,
                datasets_version=product.datasets_version,
                algorithm_version=product.algorithm_version,
                result_hash=product.result_hash,
            )
        assert_storable(case)
        await self._store.save(case)
        await self._publish(case)
        return case

    async def complete_queued(self, case_id: str) -> None:
        case = await self._store.get(case_id)
        if case is None or case.status == "completed":
            return
        product = await self._load_product(case.spec)
        case.complete(
            verdict=product.verdict,
            evidence=product.evidence,
            series=product.series,
            ai_opinion=AiOpinion(predicted_class="linear", confidence="medium"),
            profile=product.profile,
            urban=product.urban,
            catalog_version=product.catalog_version,
            datasets_version=product.datasets_version,
            algorithm_version=product.algorithm_version,
            result_hash=product.result_hash,
        )
        assert_storable(case)
        await self._store.save(case)
        await self._publish(case)

    async def compare(
        self,
        *,
        variable_id: str,
        region_ids: list[str],
        period_start: str,
        period_end: str,
        season: str | None,
        frequency: str,
        language: str,
        owner_id: str,
        role: str,
    ) -> list[Case]:
        require_compare_count(len(region_ids))
        created: list[Case] = []
        for region_id in region_ids:
            created.append(
                await self.create(
                    spec=CaseSpec(
                        variable_id=variable_id,
                        region_id=region_id,
                        period_start=period_start,
                        period_end=period_end,
                        season=season,
                        frequency=frequency,
                        language=language,
                    ),
                    owner_id=owner_id,
                    role=role,
                )
            )
        return created

    async def get(self, case_id: str, *, actor_id: str, role: str) -> Case:
        return await self._require_visible(case_id, actor_id, role)

    async def list_cases(self, *, actor_id: str, role: str) -> list[Case]:
        if role == "guest":
            return []
        owned = await self._store.list_owned(actor_id)
        return [case for case in owned if case.listed_for(actor_id, role)]

    async def delete(self, case_id: str, *, actor_id: str, role: str) -> None:
        case = await self._store.get(case_id)
        if case is None or not case.visible_to(actor_id, role):
            raise CaseError("case_not_found", "Справу не знайдено")
        case.assignment_linked = await self._assignments.is_linked(case_id)
        case.assert_deletable(actor_id, role)
        await self._store.delete(case_id)

    async def evidence(self, case_id: str, *, actor_id: str, role: str):
        case = await self._require_visible(case_id, actor_id, role)
        if case.evidence is None:
            raise CaseError("evidence_not_ready", "Протокол ще не збережено")
        return case.evidence

    async def profile(self, case_id: str, *, actor_id: str, role: str) -> VerticalProfile:
        case = await self._require_visible(case_id, actor_id, role)
        if case.profile is None:
            raise CaseError("profile_not_ready", "Профіль ще не збережено")
        return case.profile

    async def urban(self, case_id: str, *, actor_id: str, role: str) -> UrbanContrast:
        case = await self._require_visible(case_id, actor_id, role)
        if case.urban is None:
            raise CaseError("urban_not_ready", "Порівняння міста ще не збережено")
        return case.urban

    async def _known(self, spec: CaseSpec) -> None:
        if self._catalog is None:
            return
        try:
            await self._catalog.get_variable(spec.variable_id)
            await self._catalog.get_region(spec.region_id)
        except CatalogError as error:
            raise CaseError(error.code, error.message) from error

    async def _from_analytics(self, series: dict, levels: dict | None, urban: dict | None) -> AnalysisProduct:
        from earthtrend.api.infrastructure.analytics_bridge import product_from_series, run_blocking

        return await run_blocking(product_from_series, series, levels, urban)

    async def _load_product(self, spec: CaseSpec) -> AnalysisProduct:
        key = cache_key(
            spec,
            self._analysis.catalog_version,
            self._analysis.datasets_version,
            self._analysis.algorithm_version,
        )
        if self._cache is not None:
            cached = await self._cache.get_json(key)
            if cached is not None:
                return load_product(cached)
        product = await self._analysis.run(spec)
        if self._cache is not None:
            await self._cache.set_json(key, dump_product(product), PRODUCT_TTL)
        return product

    async def _publish(self, case: Case) -> None:
        if self._feedback is not None and case.status == "completed" and case.verdict is not None:
            await self._feedback.record(
                region_id=case.spec.region_id,
                case_id=case.id,
                verdict_code=case.verdict.code,
            )
        if self._remember is not None:
            await self._remember.remember(
                owner_id=case.owner_id,
                case_id=case.id,
                ephemeral=case.ephemeral,
            )
        if self._achievements is not None and case.status == "completed":
            await self._achievements.case_completed(case)

    async def _require_visible(self, case_id: str, actor_id: str, role: str) -> Case:
        case = await self._store.get(case_id)
        if case is None or not case.visible_to(actor_id, role):
            raise CaseError("case_not_found", "Справу не знайдено")
        return case


class _QueuedCases:
    def __init__(self, service: CaseService) -> None:
        self._service = service

    async def finish(self, case_id: str) -> None:
        await self._service.complete_queued(case_id)
