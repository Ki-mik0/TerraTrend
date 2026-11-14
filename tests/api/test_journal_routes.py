import asyncio

from litestar.testing import TestClient

from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app

BODY = {
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "period_start": "2000-01",
    "period_end": "2025-12",
}


def test_guest_case_is_not_saved_and_guest_cannot_write_a_note() -> None:
    app = create_app()
    with TestClient(app) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        guest = client.post("/api/v1/cases", json=BODY, headers=headers)
        assert guest.status_code == 201
        saved = client.get("/api/v1/journal/cases", headers=headers)
        assert saved.json() == []
        denied = client.post(
            "/api/v1/journal/notes",
            json={"case_id": guest.json()["id"], "text": "ні"},
            headers=headers,
        )
        assert denied.status_code == 403


def test_user_adds_and_deletes_own_note() -> None:
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="u2", username="u2", role="user", password="secret"))
    app = create_app(identity=identity)
    with TestClient(app) as client:
        owner = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        stranger = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u2", "password": "secret"}).json()["token"]
        }
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        case_id = created.json()["id"]
        remembered = client.get("/api/v1/journal/cases", headers=owner)
        assert remembered.json() == [{"case_id": case_id}]

        note = client.post(
            "/api/v1/journal/notes",
            json={"case_id": case_id, "text": "перевірити літо"},
            headers=owner,
        )
        assert note.status_code == 201
        assert note.json()["kind"] == "note"
        note_id = note.json()["id"]
        journal = client.get("/api/v1/journal", headers=owner)
        assert journal.json()["notes"][0]["text"] == "перевірити літо"
        assert journal.json()["cases"][0]["case_id"] == case_id

        hidden = client.delete(f"/api/v1/journal/notes/{note_id}", headers=stranger)
        assert hidden.status_code == 404
        removed = client.delete(f"/api/v1/journal/notes/{note_id}", headers=owner)
        assert removed.status_code == 204
        empty = client.get("/api/v1/journal", headers=owner)
        assert empty.json()["notes"] == []


def test_hypothesis_stays_when_a_stranger_writes_or_deletes() -> None:
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="u2", username="u2", role="user", password="secret"))
    app = create_app(identity=identity)
    with TestClient(app) as client:
        owner = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        stranger = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u2", "password": "secret"}).json()["token"]
        }
        case_id = client.post("/api/v1/cases", json=BODY, headers=owner).json()["id"]
        created = client.post(
            "/api/v1/journal/notes",
            json={"case_id": case_id, "text": "літо сохне", "kind": "hypothesis"},
            headers=owner,
        )
        assert created.status_code == 201
        hypothesis = created.json()
        assert hypothesis == {
            "id": hypothesis["id"],
            "author_id": "u1",
            "case_id": case_id,
            "text": "літо сохне",
            "kind": "hypothesis",
        }

        foreign = client.post(
            "/api/v1/journal/notes",
            json={"case_id": case_id, "text": "чуже", "kind": "note"},
            headers=stranger,
        )
        assert foreign.status_code == 404
        assert foreign.json()["detail"]["code"] == "case_not_found"
        rejected = client.post(
            "/api/v1/journal/notes",
            json={"case_id": case_id, "text": "висновок", "kind": "conclusion"},
            headers=owner,
        )
        assert rejected.status_code == 400
        hidden = client.delete(f"/api/v1/journal/notes/{hypothesis['id']}", headers=stranger)
        assert hidden.status_code == 404
        journal = client.get("/api/v1/journal", headers=owner)
        assert journal.json()["notes"] == [hypothesis]
        assert journal.json()["cases"] == [{"case_id": case_id}]
