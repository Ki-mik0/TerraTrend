"""Journal HTTP schemas."""

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["note", "hypothesis"]


class NoteRequest(BaseModel):
    case_id: str
    text: str = Field(min_length=1)
    kind: Kind = "note"


class NoteResponse(BaseModel):
    id: str
    author_id: str
    case_id: str
    text: str
    kind: Kind


class SavedCaseResponse(BaseModel):
    case_id: str


class JournalResponse(BaseModel):
    notes: list[NoteResponse]
    cases: list[SavedCaseResponse]
