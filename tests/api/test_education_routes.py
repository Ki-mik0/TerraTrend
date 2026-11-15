import asyncio

import pytest
from litestar.testing import TestClient

from earthtrend.api.domain.education.model import LabParams, LabRun
from earthtrend.api.infrastructure.cases.memory import MemoryAssignments
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.education.wiring import build_education_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app

CASE_BODY = {
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "period_start": "2000-01",
    "period_end": "2025-12",
}


def _app(*people: tuple[str, str], **services):
    identity = build_identity_service()
    for user_id, role in people:
        asyncio.run(identity.add_user(user_id=user_id, username=user_id, role=role, password="secret"))
    return create_app(identity=identity, **services)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    token = client.post("/api/v1/session", json={"username": username, "password": "secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _guest(client: TestClient) -> dict[str, str]:
    token = client.post("/api/v1/session/guest").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_student_cannot_create_or_read_submissions() -> None:
    with TestClient(_app(("s1", "user"))) as client:
        headers = _headers(client, "s1")
        denied = client.post(
            "/api/v1/education/assignments", json={"title": "Homework", "student_ids": ["s1"]}, headers=headers
        )
        assert denied.status_code == 403
        assert client.get("/api/v1/education/submissions", headers=headers).status_code == 403


def test_class_link_join_submit_and_badges() -> None:
    with TestClient(_app(("t1", "teacher"), ("s1", "user"), ("s2", "user"))) as client:
        teacher, student, other = (_headers(client, name) for name in ("t1", "s1", "s2"))
        case_id = client.post("/api/v1/cases", json=CASE_BODY, headers=teacher).json()["id"]
        created = client.post(
            "/api/v1/education/assignments",
            json={"title": "Soil", "case_ids": [case_id]},
            headers=teacher,
        )
        assert created.status_code == 201
        assignment_id = created.json()["id"]

        token = client.post(f"/api/v1/education/assignments/{assignment_id}/share", headers=teacher).json()["token"]
        assert token != f"share_{assignment_id}" and len(token) >= 16
        assert client.post(f"/api/v1/education/assignments/{assignment_id}/share", headers=student).status_code == 403

        opened = client.get(f"/api/v1/education/shared/{token}", headers=student).json()
        assert opened == {"id": assignment_id, "title": "Soil", "case_ids": [case_id], "joined": False}
        assert client.get("/api/v1/education/shared/nope", headers=student).status_code == 404
        joined = client.post(f"/api/v1/education/shared/{token}/join", headers=student).json()
        assert joined["joined"] is True
        assert client.post(f"/api/v1/education/shared/{token}/join", headers=_guest(client)).status_code == 403
        listed = client.get("/api/v1/education/assignments", headers=student).json()
        assert [item["id"] for item in listed] == [assignment_id]

        stranger = client.post(
            "/api/v1/education/submissions",
            json={"assignment_id": assignment_id, "case_id": case_id, "text": "done"},
            headers=other,
        )
        assert stranger.status_code == 404
        missing = client.post(
            "/api/v1/education/submissions",
            json={"assignment_id": assignment_id, "case_id": "case_missing", "text": "done"},
            headers=student,
        )
        assert missing.status_code == 404
        foreign_case = client.post("/api/v1/cases", json=CASE_BODY, headers=other).json()["id"]
        foreign = client.post(
            "/api/v1/education/submissions",
            json={"assignment_id": assignment_id, "case_id": foreign_case, "text": "done"},
            headers=student,
        )
        assert foreign.status_code == 403
        bad_demo = client.post(
            "/api/v1/education/submissions",
            json={"assignment_id": assignment_id, "case_id": case_id, "text": "done", "demo_id": "nope"},
            headers=student,
        )
        assert bad_demo.status_code == 404

        own_case = client.post("/api/v1/cases", json=CASE_BODY, headers=student).json()["id"]
        for cited in (case_id, own_case):
            submitted = client.post(
                "/api/v1/education/submissions",
                json={"assignment_id": assignment_id, "case_id": cited, "text": "done", "demo_id": "demo_arctic"},
                headers=student,
            )
            assert submitted.status_code == 201

        answers = client.get(f"/api/v1/education/submissions?assignment_id={assignment_id}", headers=teacher)
        assert [item["case_id"] for item in answers.json()] == [case_id, own_case]
        assert len(client.get("/api/v1/education/submissions", headers=teacher).json()) == 2
        assert client.get("/api/v1/education/submissions?assignment_id=nope", headers=teacher).status_code == 404

        codes = sorted(item["code"] for item in client.get("/api/v1/education/badges", headers=student).json())
        # One "assignment" badge despite two answers; the student's own likely-trend case adds the case badge.
        assert codes == ["assignment", "first_significant_trend"]


def test_demos_glossary_and_steps_by_language() -> None:
    with TestClient(_app(("s1", "user"))) as client:
        guest = _guest(client)
        uk = client.get("/api/v1/education/demos", headers=guest).json()
        en = client.get("/api/v1/education/demos?lang=en", headers=guest).json()
        assert len(uk) == len(en) == 7
        assert {item["id"] for item in uk} == {item["id"] for item in en}
        assert uk[0]["title"] != en[0]["title"] and uk[0]["steps"][0]["number"] == 1
        assert client.get("/api/v1/education/demos?lang=fr", headers=guest).status_code == 400

        one = client.get("/api/v1/education/demos/demo_arctic?lang=en", headers=guest)
        assert one.json()["tool"] == "witnesses"
        assert client.get("/api/v1/education/demos/nope", headers=guest).status_code == 404

        glossary = client.get("/api/v1/education/glossary", headers=guest).json()
        assert {"trend", "p_value", "fdr", "autocorrelation"} <= {item["id"] for item in glossary}
        assert [item["id"] for item in glossary if item["kind"] == "page"] == ["how_our_ai_works"]
        assert client.get("/api/v1/education/glossary?lang=en", headers=guest).json()[0]["term"] == "Trend"

        student = _headers(client, "s1")
        total = len(uk[0]["steps"])
        demo_id = uk[0]["id"]
        for step in range(1, total):
            progress = client.post(f"/api/v1/education/demos/{demo_id}/steps/{step}", headers=student).json()
            assert progress["finished"] is False and progress["badge"] is None
        done = client.post(f"/api/v1/education/demos/{demo_id}/steps/{total}", headers=student).json()
        assert done["finished"] is True and done["badge"] == "demo"
        again = client.post(f"/api/v1/education/demos/{demo_id}/steps/1", headers=student).json()
        assert again["badge"] is None
        assert client.post(f"/api/v1/education/demos/{demo_id}/steps/99", headers=student).status_code == 422
        assert client.post("/api/v1/education/demos/nope/steps/1", headers=student).status_code == 404
        progress = client.get(f"/api/v1/education/demos/{demo_id}/progress", headers=student).json()
        assert progress["finished"] is True and progress["steps_done"] == list(range(1, total + 1))
        fresh = client.get("/api/v1/education/demos/demo_arctic/progress", headers=student).json()
        assert fresh["steps_done"] == [] and fresh["finished"] is False
        assert client.get("/api/v1/education/demos/nope/progress", headers=student).status_code == 404


def test_quiz_hides_answers_and_awards_once() -> None:
    with TestClient(_app(("s1", "user"))) as client:
        student = _headers(client, "s1")
        quizzes = client.get("/api/v1/education/quizzes?lang=en", headers=student).json()
        assert quizzes and all(set(item) == {"id", "language", "question", "options"} for item in quizzes)
        quiz_id = "q_ai_en"
        wrong = client.post(f"/api/v1/education/quizzes/{quiz_id}", json={"choice": 0}, headers=student).json()
        assert wrong["correct"] is False and wrong["badge"] is None and wrong["explanation"]
        right = client.post(f"/api/v1/education/quizzes/{quiz_id}", json={"choice": 2}, headers=student).json()
        assert right == {**right, "correct": True, "badge": "quiz"}
        repeat = client.post(f"/api/v1/education/quizzes/{quiz_id}", json={"choice": 2}, headers=student).json()
        assert repeat["badge"] is None
        assert client.post(f"/api/v1/education/quizzes/{quiz_id}", json={"choice": 9}, headers=student).status_code == 422
        assert client.post("/api/v1/education/quizzes/nope", json={"choice": 0}, headers=student).status_code == 404
        badges = client.get("/api/v1/education/badges", headers=student).json()
        assert [item["code"] for item in badges] == ["quiz"]


def test_lab_runs_a_synthetic_series() -> None:
    with TestClient(_app(("s1", "user"))) as client:
        student = _headers(client, "s1")
        body = {"noise": 1.0, "years": 30, "autocorrelation": 0.3}
        response = client.post("/api/v1/education/lab", json=body, headers=student)
        assert response.status_code == 201
        assert response.json()["status"] == "ready"
        assert response.json()["series"]
        assert client.post("/api/v1/education/lab", json={**body, "years": 2}, headers=student).status_code == 400


class _ReadyLab:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, params: LabParams) -> LabRun:
        self.calls += 1
        return LabRun(params=params, status="ready", slope_decade=0.2, p_value=0.03, n_eff=12.5, significant=True, series=(1.0, 2.0))


def test_ready_lab_result_is_cached() -> None:
    lab = _ReadyLab()
    catalog = seed_catalog()
    education = build_education_service(lessons=catalog, lab=lab)
    with TestClient(_app(("s1", "user"), catalog=catalog, education=education)) as client:
        student = _headers(client, "s1")
        body = {"noise": 1.0, "years": 30, "autocorrelation": 0.3}
        first = client.post("/api/v1/education/lab", json=body, headers=student)
        second = client.post("/api/v1/education/lab", json=body, headers=student)
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        assert first.json()["significant"] is True and first.json()["series"] == [1.0, 2.0]
        assert lab.calls == 1


@pytest.mark.asyncio
async def test_assignment_links_case_when_port_is_present() -> None:
    links = MemoryAssignments()
    education = build_education_service(lessons=seed_catalog(), links=links)
    await education.create_assignment(
        teacher_id="t1", role="teacher", title="Linked", student_ids=["s1", "s1"], case_ids=["case_9"]
    )
    assert await links.is_linked("case_9") is True
    with pytest.raises(Exception) as error:
        await education.create_assignment(teacher_id="t1", role="teacher", title="  ", student_ids=[], case_ids=[])
    assert getattr(error.value, "code", "") == "invalid_assignment"
