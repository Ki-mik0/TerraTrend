"""PostgreSQL notes and saved cases. A repeated save of the same case writes one row."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from earthtrend.api.domain.journal.model import Note, SavedCase
from earthtrend.api.infrastructure.identity.postgres import Base


class NoteRow(Base):
    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint("kind IN ('note', 'hypothesis')", name="notes_kind_known"),
        Index("notes_author", "author_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class SavedCaseRow(Base):
    __tablename__ = "saved_cases"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class JournalCounterRow(Base):
    __tablename__ = "journal_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


def _note(row: NoteRow) -> Note:
    return Note(id=row.id, author_id=row.author_id, case_id=row.case_id, kind=row.kind, text=row.text)


class PostgresJournalStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def list_notes(self, author_id: str) -> list[Note]:
        async with self._sessions() as session:
            found = await session.scalars(
                select(NoteRow).where(NoteRow.author_id == author_id).order_by(NoteRow.id)
            )
            return [_note(row) for row in found.all()]

    async def list_saved(self, owner_id: str) -> list[SavedCase]:
        async with self._sessions() as session:
            found = await session.scalars(
                select(SavedCaseRow).where(SavedCaseRow.owner_id == owner_id).order_by(SavedCaseRow.case_id)
            )
            return [SavedCase(owner_id=row.owner_id, case_id=row.case_id) for row in found.all()]

    async def insert_note(self, *, author_id: str, case_id: str, kind: str, text: str) -> Note:
        async with self._sessions() as session:
            async with session.begin():
                number = await self._next(session, "note")
                note = Note(id=f"note_{number}", author_id=author_id, case_id=case_id, kind=kind, text=text)
                session.add(
                    NoteRow(
                        id=note.id,
                        author_id=note.author_id,
                        case_id=note.case_id,
                        kind=note.kind,
                        text=note.text,
                    )
                )
        return note

    async def get_note(self, note_id: str) -> Note | None:
        async with self._sessions() as session:
            found = await session.get(NoteRow, note_id)
            return None if found is None else _note(found)

    async def delete_note(self, note_id: str) -> None:
        async with self._sessions() as session:
            async with session.begin():
                found = await session.get(NoteRow, note_id)
                if found is not None:
                    await session.delete(found)

    async def remember(self, saved: SavedCase) -> None:
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(
                    insert(SavedCaseRow)
                    .values(owner_id=saved.owner_id, case_id=saved.case_id)
                    .on_conflict_do_nothing(index_elements=["owner_id", "case_id"])
                )

    async def _next(self, session: AsyncSession, name: str) -> int:
        row = await session.get(JournalCounterRow, name, with_for_update=True)
        if row is None:
            session.add(JournalCounterRow(name=name, value=1))
            await session.flush()
            return 1
        row.value += 1
        return row.value
