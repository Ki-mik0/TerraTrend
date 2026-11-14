import asyncio

import pytest
from litestar.testing import TestClient

from earthtrend.api.api.jobs.schemas import JobResponse
from earthtrend.api.application.jobs.service import JobService
from earthtrend.api.domain.jobs.model import JobError
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app

BODY = {
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "period_start": "2000-01",
    "period_end": "2025-12",
    "heavy": True,
}


def test_double_cancel_of_finished_job_is_rejected() -> None:
    from earthtrend.api.domain.jobs.model import Job

    job = Job(id="job_1", case_id="case_1")
    job.start()
    job.finish()
    with pytest.raises(JobError) as caught:
        job.cancel()
    assert caught.value.code == "cancel_not_allowed"


def test_heavy_case_job_runs_and_admin_lists_it() -> None:
    store = MemoryCaseStore()
    jobs = JobService(cases=store)
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="admin", username="admin", role="admin", password="secret"))
    app = create_app(cases=build_case_service(store=store, jobs=jobs), jobs=jobs, identity=identity)
    with TestClient(app) as client:
        owner = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        admin = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "admin", "password": "secret"}).json()["token"]
        }
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        assert created.status_code == 202
        assert created.headers["content-type"].startswith("application/json")
        job_id = created.json()["job_id"]
        done = None
        for _ in range(50):
            current = client.get(f"/api/v1/jobs/{job_id}", headers=owner)
            assert current.status_code == 200
            body = current.json()
            JobResponse.model_validate(body)
            assert set(body) == {"id", "case_id", "status", "progress", "stage", "message"}
            assert isinstance(body["progress"], int)
            if body["status"] == "completed":
                done = body
                break
        assert done is not None
        assert done["id"] == job_id
        assert done["case_id"] == created.json()["id"]
        assert done["progress"] == 100
        events = client.get(f"/api/v1/jobs/{job_id}/events", headers=owner)
        assert events.status_code == 200
        assert "event: completed" in events.text
        assert "load" in events.text
        assert "analyze" in events.text
        assert created.json()["id"] in events.text

        denied = client.get("/api/v1/admin/jobs", headers=owner)
        assert denied.status_code == 403
        listed = client.get("/api/v1/admin/jobs", headers=admin)
        assert listed.json()[0]["id"] == job_id
        again = client.delete(f"/api/v1/jobs/{job_id}", headers=owner)
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "cancel_not_allowed"


def test_job_requires_a_session_and_hides_a_stranger() -> None:
    store = MemoryCaseStore()
    jobs = JobService(cases=store)
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="u2", username="u2", role="user", password="secret"))
    app = create_app(cases=build_case_service(store=store, jobs=jobs), jobs=jobs, identity=identity)
    with TestClient(app) as client:
        missing = client.get("/api/v1/jobs/job_missing")
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "invalid_token"
        owner = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        stranger = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u2", "password": "secret"}).json()["token"]
        }
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        hidden = client.get(f"/api/v1/jobs/{created.json()['job_id']}", headers=stranger)
        assert hidden.status_code == 404
        assert hidden.json()["detail"]["code"] == "job_not_found"
