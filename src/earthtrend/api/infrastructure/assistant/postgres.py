"""PostgreSQL table of assistant exchanges. Generic JSON columns keep it testable on SQLite."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from earthtrend.api.domain.assistant.exchange import AssistantExchange, ToolStep


class AssistantBase(DeclarativeBase):
    pass


class ExchangeRow(AssistantBase):
    __tablename__ = "assistant_exchanges"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'answered', 'failed')", name="assistant_status_known"),
        CheckConstraint("mode IN ('investigate', 'teach')", name="assistant_mode_known"),
        Index("assistant_exchanges_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    case_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _row(exchange: AssistantExchange) -> dict[str, Any]:
    return {
        "owner_id": exchange.owner_id,
        "role": exchange.role,
        "mode": exchange.mode,
        "language": exchange.language,
        "status": exchange.status,
        "question": exchange.question,
        "answer": exchange.answer,
        "plan": [step.payload() for step in exchange.steps],
        "case_ids": list(exchange.case_ids),
        "citations": list(exchange.citations),
        "warnings": list(exchange.warnings),
        "created_at": exchange.created_at,
    }


def _exchange(row: ExchangeRow) -> AssistantExchange:
    return AssistantExchange(
        id=row.id,
        owner_id=row.owner_id,
        role=row.role,
        mode=row.mode,
        language=row.language,
        status=row.status,
        question=row.question,
        answer=row.answer,
        steps=[ToolStep(tool=item["tool"], reason=item["reason"], input=item["input"]) for item in row.plan],
        case_ids=list(row.case_ids),
        citations=list(row.citations),
        warnings=list(row.warnings),
        created_at=row.created_at,
    )


class PostgresExchangeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def save(self, exchange: AssistantExchange) -> None:
        values = _row(exchange)
        async with self._sessions() as session:
            async with session.begin():
                found = await session.get(ExchangeRow, exchange.id)
                if found is None:
                    session.add(ExchangeRow(id=exchange.id, **values))
                else:
                    for key, value in values.items():
                        setattr(found, key, value)

    async def get(self, exchange_id: str, *, owner_id: str) -> AssistantExchange | None:
        async with self._sessions() as session:
            found = await session.get(ExchangeRow, exchange_id)
        if found is None or found.owner_id != owner_id:
            return None
        return _exchange(found)

    async def list(self, *, owner_id: str, limit: int) -> list[AssistantExchange]:
        query = (
            select(ExchangeRow)
            .where(ExchangeRow.owner_id == owner_id)
            .order_by(ExchangeRow.created_at.desc(), ExchangeRow.id.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(query)).all()
        return [_exchange(row) for row in rows]
