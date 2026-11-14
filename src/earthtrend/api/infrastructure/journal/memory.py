"""In-memory journal. Tests and a process without PostgreSQL use it."""

from __future__ import annotations

from earthtrend.api.domain.journal.model import Note, SavedCase


class MemoryJournalStore:
    def __init__(self) -> None:
        self.notes: dict[str, Note] = {}
        self.saved: list[SavedCase] = []
        self._seq = 0

    async def list_notes(self, author_id: str) -> list[Note]:
        return [item for item in self.notes.values() if item.author_id == author_id]

    async def list_saved(self, owner_id: str) -> list[SavedCase]:
        return [item for item in self.saved if item.owner_id == owner_id]

    async def insert_note(self, *, author_id: str, case_id: str, kind: str, text: str) -> Note:
        self._seq += 1
        note = Note(id=f"note_{self._seq}", author_id=author_id, case_id=case_id, kind=kind, text=text)
        self.notes[note.id] = note
        return note

    async def get_note(self, note_id: str) -> Note | None:
        return self.notes.get(note_id)

    async def delete_note(self, note_id: str) -> None:
        self.notes.pop(note_id, None)

    async def remember(self, saved: SavedCase) -> None:
        if any(item.owner_id == saved.owner_id and item.case_id == saved.case_id for item in self.saved):
            return
        self.saved.append(saved)
