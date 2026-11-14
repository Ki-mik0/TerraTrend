import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager

from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.api.api.assistant.routes import assistant_router
from earthtrend.api.api.identity.routes import identity_router
from earthtrend.api.application.assistant.service import AssistantService
from earthtrend.api.domain.assistant.exchange import ToolStep
from earthtrend.api.infrastructure.assistant.memory import (
    CASE_ID,
    MemoryCatalog,
    MemoryNotes,
    MemoryRateLimiter,
)
from earthtrend.api.infrastructure.assistant.narrator import FallbackNarrator, TemplateNarrator
from earthtrend.api.infrastructure.assistant.wiring import Neighbors, build_assistant_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service

QUESTION = {"question": "Чи сохне ґрунт?", "language": "uk"}


def _service(notes: MemoryNotes | None = None, **neighbors) -> AssistantService:
    return build_assistant_service(
        notes=notes or MemoryNotes(),
        neighbors=Neighbors(**neighbors),
        narrator=FallbackNarrator(TemplateNarrator(), None),
    )


@contextmanager
def _client(service: AssistantService) -> Iterator[tuple[TestClient, dict[str, str], dict[str, str]]]:
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    app = Litestar(route_handlers=[assistant_router(service, identity), identity_router(identity)])
    with TestClient(app) as client:
        user = client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        guest = client.post("/api/v1/session/guest").json()["token"]
        yield client, {"Authorization": f"Bearer {user}"}, {"Authorization": f"Bearer {guest}"}


def _events(text: str) -> list[tuple[str, dict]]:
    found = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in lines:
            found.append((lines["event"], json.loads(lines["data"])))
    return found


def test_ask_returns_plan_cases_citations_and_history() -> None:
    notes = MemoryNotes()
    with _client(_service(notes)) as (client, user, guest):
        asked = client.post("/api/v1/assistant/ask", json=QUESTION, headers=user)
        assert asked.status_code == 201
        body = asked.json()
        assert body["case_ids"] == [CASE_ID]
        assert body["status"] == "answered" and body["mode"] == "investigate"
        assert body["citations"][0]["case_id"] == CASE_ID
        assert [step["tool"] for step in body["plan"]][:2] == ["search_variables", "analyze_case"]
        assert notes.notes[0]["case_ids"] == [CASE_ID]

        history = client.get("/api/v1/assistant/exchanges?limit=5", headers=user)
        assert history.status_code == 200
        assert [item["exchange_id"] for item in history.json()["exchanges"]] == [body["exchange_id"]]
        one = client.get(f"/api/v1/assistant/exchanges/{body['exchange_id']}", headers=user)
        assert one.status_code == 200 and one.json()["question"] == QUESTION["question"]

        assert client.get(f"/api/v1/assistant/exchanges/{body['exchange_id']}", headers=guest).status_code == 404
        assert client.get("/api/v1/assistant/exchanges", headers=guest).json() == {"exchanges": []}
        assert client.get("/api/v1/assistant/exchanges?limit=0", headers=user).status_code == 400


def test_teach_mode_returns_a_question() -> None:
    with _client(_service()) as (client, user, _):
        asked = client.post("/api/v1/assistant/ask", json={**QUESTION, "mode": "teach", "language": "en"}, headers=user)
        assert asked.status_code == 201
        assert asked.json()["answer"].endswith("?") and asked.json()["mode"] == "teach"


def test_stream_sends_every_event_in_order() -> None:
    with _client(_service()) as (client, _, guest):
        streamed = client.post("/api/v1/assistant/ask/stream", json=QUESTION, headers=guest)
        assert streamed.status_code == 200
        events = _events(streamed.text)
        names = [name for name, _ in events]
        assert names[0] == "plan" and names[-1] == "done"
        assert {"tool_start", "tool_result", "answer_chunk"} <= set(names)
        assert events[-1][1]["case_ids"] == [CASE_ID]


def test_stream_reports_an_error_event_when_a_neighbor_fails() -> None:
    class Down(MemoryCatalog):
        async def ids(self) -> set[str]:
            raise RuntimeError("down")

    with _client(_service(catalog=Down())) as (client, user, _):
        streamed = client.post("/api/v1/assistant/ask/stream", json=QUESTION, headers=user)
        assert [name for name, _ in _events(streamed.text)] == ["error"]


def test_rate_limit_and_validation_errors() -> None:
    service = _service()
    service._limiter = MemoryRateLimiter(limit=1)
    with _client(service) as (client, user, _):
        assert client.post("/api/v1/assistant/ask", json=QUESTION, headers=user).status_code == 201
        limited = client.post("/api/v1/assistant/ask", json=QUESTION, headers=user)
        assert limited.status_code == 429 and limited.json()["detail"]["code"] == "rate_limited"
        streamed = client.post("/api/v1/assistant/ask/stream", json=QUESTION, headers=user)
        assert streamed.status_code == 429

        assert client.post("/api/v1/assistant/ask", json={**QUESTION, "mode": "chat"}, headers=user).status_code == 400
        assert client.post("/api/v1/assistant/ask", json={"question": ""}, headers=user).status_code == 400
        assert client.post("/api/v1/assistant/ask", json=QUESTION).status_code == 401


def test_template_plan_is_cached_between_users() -> None:
    service = _service()
    with _client(service) as (client, user, guest):
        client.post("/api/v1/assistant/ask", json=QUESTION, headers=user)
        client.post("/api/v1/assistant/ask", json=QUESTION, headers=guest)
    assert len(service._plans.items) == 1
    cached = next(iter(service._plans.items.values()))
    assert all(isinstance(step, ToolStep) for step in cached)
