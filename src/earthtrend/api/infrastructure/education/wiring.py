"""Wire education with a memory store, or with PostgreSQL; Redis caches lessons, lab runs and badges."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import create_async_engine

from earthtrend.api.application.education.ports import (
    CaseLinkPort,
    CaseLookup,
    EducationStore,
    LabPort,
    LessonPort,
    QuizBank,
)
from earthtrend.api.application.education.service import EducationService
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.infrastructure.education.lab import StubLab
from earthtrend.api.infrastructure.education.memory import MemoryEducationStore
from earthtrend.api.infrastructure.education.quizzes import MemoryQuizBank
from earthtrend.api.infrastructure.education.sql import SqlEducationStore
from earthtrend.api.infrastructure.shared.cache import MemoryCache, cache_from_env


def build_education_service(
    *,
    lessons: LessonPort,
    store: EducationStore | None = None,
    quizzes: QuizBank | None = None,
    lab: LabPort | None = None,
    cache: CachePort | None = None,
    cases: CaseLookup | None = None,
    links: CaseLinkPort | None = None,
) -> EducationService:
    return EducationService(
        lessons=lessons,
        store=store or MemoryEducationStore(),
        quizzes=quizzes or MemoryQuizBank(),
        lab=lab or StubLab(),
        cache=cache or MemoryCache(),
        cases=cases,
        links=links,
    )


def education_from_env(
    *,
    lessons: LessonPort,
    cases: CaseLookup | None = None,
    links: CaseLinkPort | None = None,
    cache: CachePort | None = None,
) -> tuple[EducationService, Callable[[], Awaitable[None]] | None]:
    """PostgreSQL when `DB_URL` points at it, memory otherwise. Redis when `REDIS_URL` is set."""
    url = os.environ.get("DB_URL", "")
    cache = cache if cache is not None else cache_from_env()
    if url.startswith("postgresql"):
        store = SqlEducationStore(create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5))
        service = build_education_service(lessons=lessons, store=store, cache=cache, cases=cases, links=links)
        return service, store.prepare
    return build_education_service(lessons=lessons, cache=cache, cases=cases, links=links), None
