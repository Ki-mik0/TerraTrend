"""Queue, drive, cancel, and list jobs."""

from __future__ import annotations

import asyncio
from typing import Protocol

from earthtrend.api.application.identity.store import Clock
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.identity.model import allows
from earthtrend.api.domain.jobs.model import TERMINAL, Job, JobError, RetryableJobError
from earthtrend.api.infrastructure.identity.clock import SystemClock
from earthtrend.api.infrastructure.jobs.memory import MemoryJobStore
from earthtrend.api.infrastructure.jobs.runner import ProcessPoolRunner


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class JobStore(Protocol):
    async def add(self, job: Job) -> bool: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def open_for(self, case_id: str) -> Job | None: ...

    async def claim(self, job_id: str) -> Job | None: ...

    async def save(self, job: Job) -> None: ...

    async def list_all(self) -> list[Job]: ...


class JobRunner(Protocol):
    async def run(self, case_id: str) -> None: ...


class CaseFinisher(Protocol):
    async def finish(self, case_id: str) -> None: ...


class JobService:
    def __init__(
        self,
        *,
        cases: CaseLookup,
        store: JobStore | None = None,
        runner: JobRunner | None = None,
        finisher: CaseFinisher | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._cases = cases
        self._store = store if store is not None else MemoryJobStore()
        self._runner = runner if runner is not None else ProcessPoolRunner()
        self._finisher = finisher
        self._clock = clock if clock is not None else SystemClock()

    def attach_finisher(self, finisher: CaseFinisher) -> None:
        self._finisher = finisher

    async def enqueue(self, case_id: str) -> str:
        existing = await self._store.open_for(case_id)
        if existing is not None:
            return existing.id
        job = Job(id=f"job_{case_id}", case_id=case_id, created_at=self._clock.now())
        if not await self._store.add(job):
            raced = await self._store.open_for(case_id)
            return raced.id if raced is not None else job.id
        await self.drive(job.id)
        return job.id

    async def get(self, job_id: str, *, actor_id: str, role: str) -> Job:
        job = await self._store.get(job_id)
        if job is None or not await self._visible(job, actor_id, role):
            raise JobError("job_not_found", "Задачу не знайдено")
        return job

    async def stream(self, job_id: str, *, actor_id: str, role: str):
        seen = 0
        while True:
            job = await self.get(job_id, actor_id=actor_id, role=role)
            while seen < len(job.events):
                yield job.events[seen]
                seen += 1
            if job.status in TERMINAL:
                return
            await asyncio.sleep(0.02)

    async def drive(self, job_id: str) -> None:
        claimed = await self._store.claim(job_id)
        if claimed is None:
            return
        try:
            await self._runner.run(claimed.case_id)
            current = await self._require(job_id)
            if current.status == "cancelled":
                return
            current.advance("analyze", 70, "Рахуємо тренд")
            await self._store.save(current)
            await self._runner.run(current.case_id)
            current = await self._require(job_id)
            if current.status == "cancelled":
                return
            if self._finisher is not None:
                await self._finisher.finish(current.case_id)
            current.finish()
            await self._store.save(current)
        except RetryableJobError as error:
            await self._retry(job_id, error.message)
        except Exception:
            await self._fail(job_id)

    async def cancel(self, job_id: str, *, actor_id: str, role: str) -> None:
        job = await self.get(job_id, actor_id=actor_id, role=role)
        job.cancel()
        await self._store.save(job)

    async def list_all(self, *, role: str) -> list[Job]:
        if not allows(role, "admin"):
            raise JobError("forbidden", "Усі задачі бачить лише admin")
        return await self._store.list_all()

    async def _retry(self, job_id: str, message: str) -> None:
        current = await self._require(job_id)
        if current.status in TERMINAL:
            return
        if current.attempts >= 1:
            current.fail(message)
            await self._store.save(current)
            return
        current.requeue()
        await self._store.save(current)
        await self.drive(job_id)

    async def _fail(self, job_id: str) -> None:
        current = await self._store.get(job_id)
        if current is None or current.status in TERMINAL:
            return
        current.fail("Збій виконання")
        await self._store.save(current)

    async def _require(self, job_id: str) -> Job:
        job = await self._store.get(job_id)
        if job is None:
            raise JobError("job_not_found", "Задачу не знайдено")
        return job

    async def _visible(self, job: Job, actor_id: str, role: str) -> bool:
        if allows(role, "admin"):
            return True
        case = await self._cases.get(job.case_id)
        return case is not None and case.owner_id == actor_id
