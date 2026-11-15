"""List notes and saved cases. A guest case is never remembered."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.application.journal.store import JournalStore
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.journal.model import JournalError, Note, SavedCase, require_kind, require_writer


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class JournalService:
    def __init__(self, *, cases: CaseLookup, store: JournalStore) -> None:
        self._cases = cases
        self._store = store

    async def remember(self, *, owner_id: str, case_id: str, ephemeral: bool) -> None:
        if ephemeral:
            return
        await self._store.remember(SavedCase(owner_id=owner_id, case_id=case_id))

    async def list_journal(self, *, actor_id: str) -> tuple[list[Note], list[SavedCase]]:
        notes = await self._store.list_notes(actor_id)
        return notes, await self.list_cases(actor_id=actor_id)

    async def list_cases(self, *, actor_id: str) -> list[SavedCase]:
        """Saved cases that still exist: a deleted case must not stay behind as a dead link."""
        saved = await self._store.list_saved(actor_id)
        return [item for item in saved if await self._cases.get(item.case_id) is not None]

    async def add_note(
        self, *, author_id: str, role: str, case_id: str, text: str, kind: str = "note"
    ) -> Note:
        require_writer(role)
        require_kind(kind)
        case = await self._cases.get(case_id)
        if case is None or case.owner_id != author_id:
            raise JournalError("case_not_found", "Справу не знайдено")
        return await self._store.insert_note(author_id=author_id, case_id=case_id, kind=kind, text=text)

    async def delete_note(self, note_id: str, *, actor_id: str) -> None:
        note = await self._store.get_note(note_id)
        if note is None or not note.owned_by(actor_id):
            raise JournalError("note_not_found", "Нотатку не знайдено")
        await self._store.delete_note(note_id)
