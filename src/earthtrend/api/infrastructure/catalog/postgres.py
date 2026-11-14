"""PostgreSQL rows for regions a user drew, CMR passports, and potential feedback."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, Index, Integer, String, Text, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from earthtrend.api.domain.catalog.model import PotentialFeedback, Region, VariablePassport
from earthtrend.api.infrastructure.identity.postgres import Base


class CustomRegionRow(Base):
    __tablename__ = "custom_regions"
    __table_args__ = (Index("custom_regions_kind", "kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    bbox: Mapped[list] = mapped_column(JSONB, nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    geometry: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ring: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class CatalogPassportRow(Base):
    __tablename__ = "catalog_passports"
    __table_args__ = (
        CheckConstraint("level IN ('curated', 'cmr')", name="catalog_passports_level"),
        Index("catalog_passports_level_idx", "level"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_uk: Mapped[str] = mapped_column(String(200), nullable=False)
    kid_description: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[str] = mapped_column(String(32), nullable=False)
    theme: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    witnesses: Mapped[list] = mapped_column(JSONB, nullable=False)
    doi: Mapped[str] = mapped_column(String(128), nullable=False)


class FeedbackRow(Base):
    __tablename__ = "potential_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False)
    variable_id: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_sign: Mapped[int] = mapped_column(Integer, nullable=False)
    p_significant: Mapped[float] = mapped_column(Float, nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_code: Mapped[str] = mapped_column(String(32), nullable=False)


class CmrQueryRow(Base):
    __tablename__ = "cmr_queries"
    __table_args__ = (Index("cmr_queries_query", "query", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    passport_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


def _region(row: CustomRegionRow) -> Region:
    ring = tuple(row.ring) if row.ring else None
    return Region(
        id=row.id,
        name=row.name,
        kind=row.kind,
        bbox=tuple(row.bbox),  # type: ignore[arg-type]
        area_km2=row.area_km2,
        status=row.status,
        geometry=row.geometry,
        ring=ring,  # type: ignore[arg-type]
    )


def _passport(row: CatalogPassportRow) -> VariablePassport:
    return VariablePassport(
        id=row.id,
        name=row.name,
        name_uk=row.name_uk,
        kid_description=row.kid_description,
        units=row.units,
        theme=row.theme,
        domain=row.domain,
        level=row.level,
        witnesses=tuple(row.witnesses),
        doi=row.doi,
    )


class PostgresCatalogStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def save_region(self, region: Region) -> None:
        async with self._sessions.begin() as session:
            session.add(
                CustomRegionRow(
                    id=region.id,
                    name=region.name,
                    kind=region.kind,
                    bbox=list(region.bbox),
                    area_km2=region.area_km2,
                    status=region.status,
                    geometry=region.geometry,
                    ring=list(region.ring) if region.ring else None,
                )
            )

    async def list_regions(self) -> list[Region]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(CustomRegionRow))).all()
        return [_region(row) for row in rows]

    async def clear_regions(self) -> None:
        async with self._sessions.begin() as session:
            await session.execute(delete(CustomRegionRow))

    async def save_feedback(self, item: PotentialFeedback) -> None:
        async with self._sessions.begin() as session:
            session.add(
                FeedbackRow(
                    region_id=item.region_id,
                    variable_id=item.variable_id,
                    predicted_sign=item.predicted_sign,
                    p_significant=item.p_significant,
                    case_id=item.case_id,
                    actual_code=item.actual_code,
                )
            )

    async def list_feedback(self) -> list[PotentialFeedback]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(FeedbackRow))).all()
        return [
            PotentialFeedback(
                region_id=row.region_id,
                variable_id=row.variable_id,
                predicted_sign=row.predicted_sign,
                p_significant=row.p_significant,
                case_id=row.case_id,
                actual_code=row.actual_code,
            )
            for row in rows
        ]

    async def save_passport(self, item: VariablePassport) -> None:
        async with self._sessions.begin() as session:
            found = await session.get(CatalogPassportRow, item.id)
            if found is None:
                session.add(
                    CatalogPassportRow(
                        id=item.id,
                        name=item.name,
                        name_uk=item.name_uk,
                        kid_description=item.kid_description,
                        units=item.units,
                        theme=item.theme,
                        domain=item.domain,
                        level=item.level,
                        witnesses=list(item.witnesses),
                        doi=item.doi,
                    )
                )
                return
            found.name = item.name
            found.level = item.level

    async def list_passports(self) -> list[VariablePassport]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(CatalogPassportRow))).all()
        return [_passport(row) for row in rows]

    async def save_query(self, query_id: str, query: str, passport_id: str) -> None:
        async with self._sessions() as session:
            session.add(CmrQueryRow(id=query_id, query=query[:200], passport_id=passport_id, status="completed"))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
