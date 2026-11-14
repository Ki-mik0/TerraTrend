"""A note belongs to its author. A saved case is only a reference."""

from __future__ import annotations

from dataclasses import dataclass

KINDS = frozenset({"note", "hypothesis"})


class JournalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def require_kind(kind: str) -> None:
    if kind not in KINDS:
        raise JournalError("kind_invalid", "Невідомий вид нотатки")


@dataclass
class Note:
    id: str
    author_id: str
    case_id: str
    text: str
    kind: str = "note"

    def __post_init__(self) -> None:
        require_kind(self.kind)

    def owned_by(self, actor_id: str) -> bool:
        return self.author_id == actor_id


@dataclass(frozen=True)
class SavedCase:
    owner_id: str
    case_id: str


def require_writer(role: str) -> None:
    if role == "guest":
        raise JournalError("forbidden", "Гість не пише в журнал")
