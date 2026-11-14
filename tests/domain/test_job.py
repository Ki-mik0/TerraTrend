"""Job rules without a database."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from earthtrend.api.application.jobs.service import JobService
from earthtrend.api.domain.jobs.model import Job, JobError, RetryableJobError
from earthtrend.api.infrastructure.jobs.memory import MemoryJobStore
from earthtrend.api.infrastructure.jobs.pool import execute_heavy
from earthtrend.api.infrastructure.jobs.runner import ProcessPoolRunner


class FixedClock:
    def __init__(self) -> None:
        self.moment = datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.moment


class Lookup:
    async def get(self, case_id: str):
        return None


class Scripted:
    def __init__(self, effects: list[Exception | None]) -> None:
        self.effects = list(effects)
        self.calls = 0

    async def run(self, case_id: str) -> None:
        self.calls += 1
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect


class Hold:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run(self, case_id: str) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


def _service(runner) -> JobService:
    return JobService(cases=Lookup(), store=MemoryJobStore(), runner=runner, clock=FixedClock())


def test_finished_job_cannot_be_cancelled() -> None:
    job = Job(id="job_1", case_id="case_1")
    job.claim()
    job.advance("analyze", 70, "Рахуємо тренд")
    job.finish()
    with pytest.raises(JobError) as caught:
        job.cancel()
    assert caught.value.code == "cancel_not_allowed"
    assert [event["data"]["stage"] for event in job.events if event["event"] == "progress"] == [
        "queued",
        "load",
        "analyze",
    ]


def test_retryable_failure_runs_once_more_and_then_fails() -> None:
    runner = Scripted([RetryableJobError("Тимчасовий збій"), RetryableJobError("Тимчасовий збій")])
    service = _service(runner)

    async def scenario() -> Job:
        job_id = await service.enqueue("case_1")
        found = await service._store.get(job_id)
        assert found is not None
        return found

    job = asyncio.run(scenario())
    assert runner.calls == 2
    assert job.status == "failed"
    assert job.attempts == 1
    assert job.message == "Тимчасовий збій"
    assert job.created_at == datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)


def test_unknown_failure_does_not_retry() -> None:
    runner = Scripted([RuntimeError("secret-token")])
    service = _service(runner)

    async def scenario() -> Job:
        job_id = await service.enqueue("case_2")
        found = await service._store.get(job_id)
        assert found is not None
        return found

    job = asyncio.run(scenario())
    assert job.status == "failed"
    assert job.attempts == 0
    assert job.message == "Збій виконання"
    assert "secret-token" not in job.message


def test_cancel_stops_the_running_job() -> None:
    runner = Hold()
    service = _service(runner)

    async def scenario() -> str:
        task = asyncio.create_task(service.enqueue("case_3"))
        await runner.started.wait()
        job = await service._store.get("job_case_3")
        assert job is not None
        job.cancel()
        await service._store.save(job)
        runner.release.set()
        await task
        return "job_case_3"

    job_id = asyncio.run(scenario())
    job = asyncio.run(service._store.get(job_id))
    assert job is not None
    assert job.status == "cancelled"
    assert runner.calls == 1


def test_process_pool_returns_the_case_id() -> None:
    runner = ProcessPoolRunner()

    async def scenario() -> None:
        await runner.run("case_pool")

    asyncio.run(scenario())
    runner.close()
    assert execute_heavy("case_pool") == "case_pool"
