"""Journal HTTP routes."""

from __future__ import annotations

from litestar import Request, Router, delete, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, JSONBody

from earthtrend.api.api.journal.schemas import JournalResponse, NoteRequest, NoteResponse, SavedCaseResponse
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.application.journal.service import JournalService
from earthtrend.api.domain.journal.model import JournalError, Note, SavedCase


def _http(error: JournalError) -> HTTPException:
    status = {"forbidden": 403, "kind_invalid": 422}.get(error.code, 404)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _note(item: Note) -> NoteResponse:
    return NoteResponse(
        id=item.id, author_id=item.author_id, case_id=item.case_id, text=item.text, kind=item.kind
    )


def _saved(item: SavedCase) -> SavedCaseResponse:
    return SavedCaseResponse(case_id=item.case_id)


def journal_router(service: JournalService, identity: IdentityService) -> Router:
    @get("/journal")
    async def list_journal(request: Request) -> JournalResponse:
        actor = await require_actor(request, identity)
        notes, saved = await service.list_journal(actor_id=actor.id)
        return JournalResponse(notes=[_note(item) for item in notes], cases=[_saved(item) for item in saved])

    @get("/journal/cases")
    async def list_saved_cases(request: Request) -> list[SavedCaseResponse]:
        actor = await require_actor(request, identity)
        return [_saved(item) for item in await service.list_cases(actor_id=actor.id)]

    @post("/journal/notes")
    async def add_note(data: JSONBody[NoteRequest], request: Request) -> NoteResponse:
        actor = await require_actor(request, identity)
        try:
            note = await service.add_note(
                author_id=actor.id,
                role=actor.role,
                case_id=data.case_id,
                text=data.text,
                kind=data.kind,
            )
        except JournalError as error:
            raise _http(error) from error
        return _note(note)

    @delete("/journal/notes/{note_id:str}", status_code=204)
    async def delete_note(note_id: FromPath[str], request: Request) -> None:
        actor = await require_actor(request, identity)
        try:
            await service.delete_note(note_id, actor_id=actor.id)
        except JournalError as error:
            raise _http(error) from error

    return Router(path="/api/v1", route_handlers=[list_journal, list_saved_cases, add_note, delete_note])
