"""Port for notes and saved cases. Memory and PostgreSQL both implement it."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.journal.model import Note, SavedCase


class JournalStore(Protocol):
    async def list_notes(self, author_id: str) -> list[Note]: ...

    async def list_saved(self, owner_id: str) -> list[SavedCase]: ...

    async def insert_note(self, *, author_id: str, case_id: str, kind: str, text: str) -> Note: ...

    async def get_note(self, note_id: str) -> Note | None: ...

    async def delete_note(self, note_id: str) -> None: ...

    async def remember(self, saved: SavedCase) -> None: ...
