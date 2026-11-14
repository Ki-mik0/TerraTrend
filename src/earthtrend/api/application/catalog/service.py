"""Catalog use cases."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.catalog.model import (
    CatalogError,
    DemoScenario,
    GlossaryEntry,
    PotentialFeedback,
    ProcessLink,
    Region,
    SensorEvent,
    TrendPotential,
    VariablePassport,
    register_region,
)


class SearchPort(Protocol):
    async def embed(self, query: str) -> list[str] | None: ...


class CatalogStore(Protocol):
    async def save_region(self, region: Region) -> None: ...

    async def list_regions(self) -> list[Region]: ...

    async def clear_regions(self) -> None: ...

    async def save_feedback(self, item: PotentialFeedback) -> None: ...

    async def list_feedback(self) -> list[PotentialFeedback]: ...

    async def save_passport(self, item: VariablePassport) -> None: ...

    async def list_passports(self) -> list[VariablePassport]: ...

    async def save_query(self, query_id: str, query: str, passport_id: str) -> None: ...


class CatalogCache(Protocol):
    async def get_json(self, key: str): ...

    async def set_json(self, key: str, value, ttl: int) -> None: ...


class CmrResult:
    def __init__(self, passport_id: str, job_id: str | None) -> None:
        self.passport_id = passport_id
        self.job_id = job_id


class CatalogService:
    def __init__(
        self,
        *,
        passports: dict[str, VariablePassport],
        regions: dict[str, Region],
        potentials: list[TrendPotential],
        demos: list[DemoScenario],
        glossary: list[GlossaryEntry],
        search: SearchPort,
        links: list[ProcessLink] | None = None,
        events: list[SensorEvent] | None = None,
        cache: CatalogCache | None = None,
    ) -> None:
        self.passports = passports
        self.regions = regions
        self.potentials = potentials
        self.demos = demos
        self.glossary = glossary
        self.links = list(links or [])
        self.events = list(events or [])
        self._search = search
        self._cache = cache
        self._store: CatalogStore | None = None
        self._runner = None
        self.feedback: list[PotentialFeedback] = []
        self._cmr: dict[str, VariablePassport] = {}
        self._seed = (
            dict(passports),
            dict(regions),
            list(potentials),
            list(demos),
            list(glossary),
        )
        self._seq = 0
        self.generation = 1

    def attach_store(self, store: CatalogStore) -> None:
        self._store = store

    def attach_runner(self, runner) -> None:
        self._runner = runner

    async def load_overlay(self) -> None:
        if self._store is None:
            return
        for item in await self._store.list_passports():
            self._cmr[item.id] = item
            self.passports[item.id] = item
        for region in await self._store.list_regions():
            self.regions[region.id] = region
        self.feedback = await self._store.list_feedback()

    async def list_variables(
        self,
        query: str | None = None,
        theme: str | None = None,
        domain: str | None = None,
        level: str | None = None,
    ) -> list[VariablePassport]:
        key = f"catalog:v{self.generation}:vars:{query}:{theme}:{domain}:{level}"
        cached = await self._read_cache(key)
        if cached is not None:
            return [_passport_from(item) for item in cached]
        items = [
            item
            for item in self.passports.values()
            if (theme is None or item.theme == theme)
            and (domain is None or item.domain == domain)
            and (level is None or item.level == level)
        ]
        if query:
            embedded = await self._search.embed(query)
            if embedded is not None:
                wanted = set(embedded)
                items = [item for item in items if item.id in wanted]
            else:
                lexical = await self._lexical(query, [item.id for item in items])
                if lexical:
                    order = {item_id: index for index, item_id in enumerate(lexical)}
                    items = sorted((item for item in items if item.id in order), key=lambda item: order[item.id])
                else:
                    items = [item for item in items if item.matches_text(query)]
        await self._write_cache(key, [_passport_dict(item) for item in items])
        return items

    async def get_variable(self, variable_id: str) -> VariablePassport:
        key = f"catalog:v{self.generation}:var:{variable_id}"
        cached = await self._read_cache(key)
        if cached is not None:
            return _passport_from(cached)
        found = self.passports.get(variable_id)
        if found is None:
            raise CatalogError("variable_not_found", "Змінну не знайдено")
        await self._write_cache(key, _passport_dict(found))
        return found

    def links_for(self, variable_id: str) -> list[ProcessLink]:
        return [item for item in self.links if item.source_id == variable_id or item.target_id == variable_id]

    def events_for(self, variable_id: str) -> list[SensorEvent]:
        found = self.passports.get(variable_id)
        if found is None:
            return []
        needle = variable_id.split("_")[0]
        return [item for item in self.events if item.instrument in {needle, variable_id}]

    async def list_regions(self, query: str | None = None) -> list[Region]:
        items = list(self.regions.values())
        if not query:
            return items
        needle = query.casefold()
        return [item for item in items if needle in item.id.casefold() or needle in item.name.casefold()]

    async def get_region(self, region_id: str) -> Region:
        found = self.regions.get(region_id)
        if found is None:
            raise CatalogError("region_not_found", "Регіон не знайдено")
        return found

    async def potential(self, region_id: str) -> list[TrendPotential]:
        region = await self.get_region(region_id)
        learned = await self._learned_potential(region)
        if learned:
            return learned
        return [item for item in self.potentials if item.region_id == region_id]

    async def _lexical(self, query: str, ids: list[str]) -> list[str]:
        from earthtrend.analytics.ml.varsearch import search_variables
        from earthtrend.api.infrastructure.analytics_bridge import run_blocking

        def _run() -> list[str]:
            page = search_variables(query, allowed_ids=ids)
            return [item.variable_id for item in page.items]

        try:
            return await run_blocking(_run)
        except Exception:
            return []

    async def _learned_potential(self, region: Region) -> list[TrendPotential]:
        from earthtrend.analytics.ml.potential import predict_potential
        from earthtrend.analytics.ml.potential_models import RegionFeatures, VariableInfo
        from earthtrend.api.infrastructure.analytics_bridge import run_blocking

        west, south, east, north = region.bbox
        features = RegionFeatures(
            region_id=region.id,
            lat=(south + north) / 2,
            lon=(west + east) / 2,
            area_km2=max(region.area_km2, 1.0),
        )
        variables = [
            VariableInfo(variable_id=item.id, concept_id=item.id, domain=item.domain or item.theme or "land")
            for item in self.passports.values()
        ]

        def _run():
            return predict_potential(features, variables)

        try:
            page = await run_blocking(_run)
        except Exception:
            return []
        if not page.items:
            return []
        return [
            TrendPotential(
                region_id=region.id,
                variable_id=item.variable_id,
                season=item.season,
                p_significant=item.p_significant,
                expected_sign=item.expected_sign,
                reasons=tuple(item.top_reasons),
            )
            for item in page.items
        ]

    async def register_custom(
        self,
        *,
        name: str,
        bbox: tuple[float, float, float, float] | None,
        geometry: dict | None,
        point: tuple[float, float] | None = None,
        radius_km: float | None = None,
    ) -> Region:
        self._seq += 1
        region = register_region(
            region_id=f"reg_{self._seq}",
            name=name,
            bbox=bbox,
            geometry=geometry,
            point=point,
            radius_km=radius_km,
        )
        self.regions[region.id] = region
        if self._store is not None:
            await self._store.save_region(region)
        return region

    async def record(self, *, region_id: str, case_id: str, verdict_code: str) -> None:
        hints = [item for item in self.potentials if item.region_id == region_id]
        for hint in hints:
            item = PotentialFeedback(
                region_id=region_id,
                variable_id=hint.variable_id,
                predicted_sign=hint.expected_sign,
                p_significant=hint.p_significant,
                case_id=case_id,
                actual_code=verdict_code,
            )
            self.feedback.append(item)
            if self._store is not None:
                await self._store.save_feedback(item)

    async def search_cmr(self, query: str) -> CmrResult:
        needle = query.strip()
        if not needle:
            raise CatalogError("query_empty", "Порожній запит")
        found = self._existing_passport(needle)
        if found is not None:
            return CmrResult(found.id, None)
        slug = await self._runner.run(needle) if self._runner is not None else _slug(needle)
        if slug in self.passports:
            return CmrResult(slug, None)
        self._seq += 1
        job_id = f"cmr_{self._seq}"
        passport = VariablePassport(
            id=slug,
            name=needle,
            name_uk=needle,
            kid_description="Знайдено в каталозі CMR.",
            units="1",
            theme="cmr",
            domain="cmr",
            level="cmr",
        )
        self.passports[passport.id] = passport
        self._cmr[passport.id] = passport
        self.generation += 1
        if self._store is not None:
            await self._store.save_passport(passport)
            await self._store.save_query(job_id, needle, passport.id)
        return CmrResult(passport.id, job_id)

    def _existing_passport(self, query: str) -> VariablePassport | None:
        folded = query.casefold()
        if folded in self.passports:
            return self.passports[folded]
        hits = [item for item in self.passports.values() if item.matches_text(query)]
        if len(hits) == 1:
            return hits[0]
        return None

    async def reload(self, *, role: str) -> int:
        if role != "admin":
            raise CatalogError("forbidden", "Каталог перечитує лише admin")
        passports, regions, potentials, demos, glossary = self._seed
        self.passports = dict(passports)
        self.passports.update(self._cmr)
        self.regions = dict(regions)
        self.potentials = list(potentials)
        self.demos = list(demos)
        self.glossary = list(glossary)
        if self._store is not None:
            await self._store.clear_regions()
        self.generation += 1
        return self.generation

    async def _read_cache(self, key: str):
        if self._cache is None:
            return None
        return await self._cache.get_json(key)

    async def _write_cache(self, key: str, value) -> None:
        if self._cache is None:
            return
        await self._cache.set_json(key, value, 60)

    async def list_demos(self, language: str | None = None) -> list[DemoScenario]:
        return [item for item in self.demos if language is None or item.language == language]

    async def list_glossary(self, language: str | None = None) -> list[GlossaryEntry]:
        return [item for item in self.glossary if language is None or item.language == language]

    async def lessons_version(self) -> int:
        """Changes on every catalog reload, so cached lessons from the old catalog are never read."""
        return self.generation


def _slug(query: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in query.casefold())
    compact = "_".join(part for part in cleaned.split("_") if part)
    return compact[:64] or "cmr_item"


def _passport_dict(item: VariablePassport) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "name_uk": item.name_uk,
        "kid_description": item.kid_description,
        "units": item.units,
        "theme": item.theme,
        "domain": item.domain,
        "level": item.level,
        "witnesses": list(item.witnesses),
        "doi": item.doi,
    }


def _passport_from(raw: dict) -> VariablePassport:
    return VariablePassport(
        id=raw["id"],
        name=raw["name"],
        name_uk=raw["name_uk"],
        kid_description=raw["kid_description"],
        units=raw["units"],
        theme=raw.get("theme", ""),
        domain=raw.get("domain", ""),
        level=raw.get("level", "curated"),
        witnesses=tuple(raw.get("witnesses", ())),
        doi=raw.get("doi", ""),
    )
