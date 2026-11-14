"""PostgreSQL cases. The product is stored; the trend is not recomputed."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from earthtrend.api.domain.cases.codec import dump_case_result, dump_spec, load_case
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.infrastructure.identity.postgres import Base


class CaseRow(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="cases_status_known",
        ),
        Index("cases_owner", "owner_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    variable_id: Mapped[str] = mapped_column(String(64), nullable=False)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    ephemeral: Mapped[bool] = mapped_column(nullable=False)
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    verdict_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(32), nullable=False)
    datasets_version: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class CaseCounterRow(Base):
    __tablename__ = "case_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


def _case(row: CaseRow) -> Case:
    return load_case(
        case_id=row.id,
        owner_id=row.owner_id,
        status=row.status,
        ephemeral=row.ephemeral,
        spec=row.spec_json,
        verdict_code=row.verdict_code,
        result=row.result_json,
        catalog_version=row.catalog_version,
        datasets_version=row.datasets_version,
        algorithm_version=row.algorithm_version,
        result_hash=row.result_hash,
    )


class PostgresCaseStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def next_id(self) -> str:
        async with self._sessions() as session:
            async with session.begin():
                number = await self._next(session, "case")
        return f"case_{number}"

    async def save(self, case: Case) -> None:
        payload = {
            "owner_id": case.owner_id,
            "variable_id": case.spec.variable_id,
            "region_id": case.spec.region_id,
            "status": case.status,
            "ephemeral": case.ephemeral,
            "spec_json": dump_spec(case.spec),
            "verdict_code": None if case.verdict is None else case.verdict.code,
            "result_json": dump_case_result(case),
            "catalog_version": case.catalog_version,
            "datasets_version": case.datasets_version,
            "algorithm_version": case.algorithm_version,
            "result_hash": case.result_hash,
        }
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(CaseRow, case.id)
                if row is None:
                    session.add(CaseRow(id=case.id, **payload))
                    return
                for key, value in payload.items():
                    setattr(row, key, value)

    async def get(self, case_id: str) -> Case | None:
        async with self._sessions() as session:
            found = await session.get(CaseRow, case_id)
            return None if found is None else _case(found)

    async def delete(self, case_id: str) -> None:
        async with self._sessions() as session:
            async with session.begin():
                found = await session.get(CaseRow, case_id)
                if found is not None:
                    await session.delete(found)

    async def list_owned(self, owner_id: str) -> list[Case]:
        async with self._sessions() as session:
            found = await session.scalars(
                select(CaseRow).where(CaseRow.owner_id == owner_id).order_by(CaseRow.id)
            )
            return [_case(row) for row in found.all()]

    async def _next(self, session: AsyncSession, name: str) -> int:
        row = await session.get(CaseCounterRow, name, with_for_update=True)
        if row is None:
            session.add(CaseCounterRow(name=name, value=1))
            await session.flush()
            return 1
        row.value += 1
        return row.value
