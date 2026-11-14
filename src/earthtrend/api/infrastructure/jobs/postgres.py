"""PostgreSQL job queue. Claiming a row is one update, so two workers cannot run it."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from earthtrend.api.domain.jobs.model import Job
from earthtrend.api.infrastructure.identity.postgres import Base


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="jobs_status_known",
        ),
        Index("jobs_status", "status"),
        Index("jobs_case", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    events: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


def _job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        case_id=row.case_id,
        status=row.status,
        progress=row.progress,
        stage=row.stage,
        message=row.message,
        attempts=row.attempts,
        created_at=row.created_at,  # type: ignore[arg-type]
        events=list(row.events),
    )


def _apply(row: JobRow, job: Job) -> None:
    row.case_id = job.case_id
    row.status = job.status
    row.progress = job.progress
    row.stage = job.stage
    row.message = job.message
    row.attempts = job.attempts
    row.events = list(job.events)


class PostgresJobStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def add(self, job: Job) -> bool:
        try:
            async with self._sessions() as session:
                async with session.begin():
                    session.add(
                        JobRow(
                            id=job.id,
                            case_id=job.case_id,
                            status=job.status,
                            progress=job.progress,
                            stage=job.stage,
                            message=job.message,
                            attempts=job.attempts,
                            events=list(job.events),
                            created_at=job.created_at,
                        )
                    )
        except IntegrityError:
            return False
        return True

    async def get(self, job_id: str) -> Job | None:
        async with self._sessions() as session:
            row = await session.get(JobRow, job_id)
        return None if row is None else _job(row)

    async def open_for(self, case_id: str) -> Job | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(JobRow).where(
                    JobRow.case_id == case_id,
                    JobRow.status.in_(("queued", "running")),
                )
            )
        return None if row is None else _job(row)

    async def claim(self, job_id: str) -> Job | None:
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(JobRow, job_id, with_for_update=True)
                if row is None or row.status != "queued":
                    return None
                job = _job(row)
                job.claim()
                _apply(row, job)
                return job

    async def save(self, job: Job) -> None:
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(JobRow, job.id, with_for_update=True)
                if row is None:
                    return
                _apply(row, job)

    async def list_all(self) -> list[Job]:
        async with self._sessions() as session:
            rows = await session.scalars(select(JobRow).order_by(JobRow.id))
            return [_job(row) for row in rows.all()]
