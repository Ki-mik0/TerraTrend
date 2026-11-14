import asyncio

from litestar.testing import TestClient

from earthtrend.api.api.identity.schemas import KeyResponse, ReviewResponse, SessionReadResponse, SessionResponse
from earthtrend.api.domain.cases.model import AiOpinion, Case, CaseSpec
from earthtrend.api.domain.identity.model import allows
from earthtrend.api.infrastructure.identity.wiring import MemoryCaseLookup, build_identity_service
from earthtrend.api.main import create_app


def _case(case_id: str, disagrees: bool) -> Case:
    return Case(
        id=case_id,
        owner_id="u1",
        role="user",
        spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"),
        ai_opinion=AiOpinion(predicted_class="step", confidence="high", disagrees=disagrees),
    )


def test_role_matrix_keeps_guest_below_user_actions() -> None:
    assert allows("guest", "view_radar") is True
    assert allows("guest", "export") is False
    assert allows("teacher", "teach") is True
    assert allows("user", "admin") is False
    assert allows("admin", "admin") is True


def test_session_keys_audit_and_review() -> None:
    lookup = MemoryCaseLookup(
        {
            "plain": _case("plain", False),
            "split": _case("split", True),
        }
    )
    identity = build_identity_service(lookup)
    asyncio.run(identity.add_user(user_id="admin-1", username="ada", role="admin", password="secret"))
    asyncio.run(identity.add_user(user_id="owner-1", username="bea", role="user", password="secret"))
    app = create_app(identity=identity)
    with TestClient(app) as client:
        denied = client.post("/api/v1/session", json={"username": "ada", "password": "wrong"})
        assert denied.status_code == 401
        opened = client.post("/api/v1/session", json={"username": "ada", "password": "secret"})
        assert opened.status_code == 201
        assert opened.headers["content-type"].startswith("application/json")
        assert set(opened.json()) == {"token"}
        SessionResponse.model_validate(opened.json())
        token = opened.json()["token"]
        read = client.get("/api/v1/session", headers={"Authorization": f"Bearer {token}"})
        assert read.status_code == 200
        assert set(read.json()) == {"user_id", "role"}
        SessionReadResponse.model_validate(read.json())
        assert read.json()["role"] == "admin"
        assert read.json()["user_id"] == "admin-1"

        user = client.post("/api/v1/session", json={"username": "bea", "password": "secret"}).json()["token"]
        blocked = client.post(
            "/api/v1/admin/api-keys",
            json={"owner_id": "owner-1"},
            headers={"Authorization": f"Bearer {user}"},
        )
        assert blocked.status_code == 403
        issued = client.post(
            "/api/v1/admin/api-keys",
            json={"owner_id": "owner-1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert issued.status_code == 201
        assert set(issued.json()) == {"id", "secret", "revoked"}
        KeyResponse.model_validate(issued.json())
        assert issued.json()["secret"] not in issued.json()["id"]
        key_id = issued.json()["id"]
        revoked = client.delete(
            f"/api/v1/admin/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 204
        again = client.delete(
            f"/api/v1/admin/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert again.status_code == 404
        assert again.json()["detail"]["code"] == "key_not_found"
        assert [item.action for item in identity.audit] == ["issue_key", "revoke_key"]

        skipped = client.post(
            "/api/v1/admin/ai-reviews",
            json={"case_id": "plain", "note": "ні"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert skipped.status_code == 409
        saved = client.post(
            "/api/v1/admin/ai-reviews",
            json={"case_id": "split", "note": "перевірити"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert saved.status_code == 201
        ReviewResponse.model_validate(saved.json())
        assert set(saved.json()) == {"id", "case_id", "actor_id", "note"}
        assert identity.reviews[0].case_id == "split"
        assert identity.reviews[0].note == "перевірити"


def test_session_rejects_a_forged_role_a_missing_token_and_echoes_no_secret() -> None:
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="owner-1", username="bea", role="user", password="secret"))
    app = create_app(identity=identity)
    with TestClient(app) as client:
        forged = client.post(
            "/api/v1/session",
            json={"username": "bea", "password": "secret", "role": "admin"},
        )
        assert forged.status_code in {400, 422}
        assert "secret" not in forged.text
        assert "password_hash" not in forged.text

        weird = client.post(
            "/api/v1/session",
            json={"username": "bea' OR '1'='1", "password": "secret"},
        )
        assert weird.status_code == 401
        assert weird.json()["detail"] == {"code": "invalid_credentials", "message": "Невірний пароль"}
        assert "secret" not in weird.text

        missing = client.post("/api/v1/admin/api-keys", json={"owner_id": "owner-1"})
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "invalid_token"

        opened = client.post("/api/v1/session", json={"username": "bea", "password": "secret"})
        assert opened.json() and SessionReadResponse.model_validate(
            client.get(
                "/api/v1/session",
                headers={"Authorization": f"Bearer {opened.json()['token']}"},
            ).json()
        ).role == "user"


def test_register_issues_a_user_token_and_rejects_a_second_name() -> None:
    identity = build_identity_service()
    app = create_app(identity=identity)
    with TestClient(app) as client:
        created = client.post("/api/v1/session/register", json={"username": "ada", "password": "secret"})
        assert created.status_code == 201
        assert created.headers["content-type"].startswith("application/json")
        assert set(created.json()) == {"token"}
        assert "secret" not in created.text
        assert "password_hash" not in created.text
        SessionResponse.model_validate(created.json())
        session = client.get("/api/v1/session", headers={"Authorization": f"Bearer {created.json()['token']}"})
        assert session.status_code == 200
        body = SessionReadResponse.model_validate(session.json())
        assert body.user_id == "user-1"
        assert body.role == "user"
        opened = client.post("/api/v1/session", json={"username": "ada", "password": "secret"})
        assert opened.status_code == 201
        again = SessionReadResponse.model_validate(
            client.get("/api/v1/session", headers={"Authorization": f"Bearer {opened.json()['token']}"}).json()
        )
        assert again.user_id == "user-1" and again.role == "user"
        taken = client.post("/api/v1/session/register", json={"username": "ada", "password": "other"})
        assert taken.status_code == 409
        assert taken.json()["detail"] == {"code": "username_taken", "message": "Ім’я вже зайняте"}
        assert sum(item.role == "user" and item.username == "ada" for item in identity._store.users.values()) == 1
        forged = client.post(
            "/api/v1/session/register",
            json={"username": "bea", "password": "secret", "role": "admin"},
        )
        assert forged.status_code in {400, 422}
        assert "bea" not in {item.username for item in identity._store.users.values()}
        empty = client.post("/api/v1/session/register", json={"username": "bea", "password": ""})
        assert empty.status_code == 422
        assert empty.json()["detail"]["code"] == "password_empty"
        assert "bea" not in {item.username for item in identity._store.users.values()}
