"""In-memory job queue for tests and a process without PostgreSQL."""

from __future__ import annotations

from earthtrend.api.domain.jobs.model import Job


class MemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def add(self, job: Job) -> bool:
        if job.id in self.jobs:
            return False
        self.jobs[job.id] = job
        return True

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def open_for(self, case_id: str) -> Job | None:
        return next(
            (job for job in self.jobs.values() if job.case_id == case_id and job.status in {"queued", "running"}),
            None,
        )

    async def claim(self, job_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.status != "queued":
            return None
        job.claim()
        return job

    async def save(self, job: Job) -> None:
        self.jobs[job.id] = job

    async def list_all(self) -> list[Job]:
        return list(self.jobs.values())
