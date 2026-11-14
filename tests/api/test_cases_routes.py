from litestar.testing import TestClient

import asyncio

from earthtrend.api.infrastructure.cases.memory import MemoryAssignments, MemoryCaseStore, MemoryJobs
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app


def _app(cases, people: tuple[tuple[str, str], ...]):
    identity = build_identity_service()
    for user_id, role in people:
        asyncio.run(identity.add_user(user_id=user_id, username=user_id, role=role, password="secret"))
    return identity, create_app(cases=cases, identity=identity)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    token = client.post("/api/v1/session", json={"username": username, "password": "secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}

BODY = {
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "period_start": "2000-01",
    "period_end": "2025-12",
}


def test_light_case_returns_verdict_and_same_evidence_version() -> None:
    _identity, app = _app(build_case_service(), (("u1", "user"),))
    with TestClient(app) as client:
        headers = _headers(client, "u1")
        created = client.post("/api/v1/cases", json=BODY, headers=headers)
        assert created.status_code == 201
        payload = created.json()
        assert payload["status"] == "completed"
        assert payload["verdict"]["code"] == "strong"
        assert payload["verdict"]["ruleset"] == "verdict_rules_v1"
        evidence = client.get(f"/api/v1/cases/{payload['id']}/evidence", headers=headers)
        assert evidence.status_code == 200
        body = evidence.json()
        assert body["version"] == payload["evidence_version"]
        assert body["verdict_code"] == "strong"
        assert body["witnesses_confirmed"] == 3
        assert body["witnesses_total"] == 3
        assert body["alibi_b_raw"] == -0.21
        assert body["quality"]["n_eff"] == 80
        assert len(body["months"]) == 12
        assert body["gam_accelerating"] is False
        assert body["alibi_b_raw"] != -0.03


def test_heavy_case_returns_job() -> None:
    jobs = MemoryJobs()
    _identity, app = _app(build_case_service(jobs=jobs), (("u1", "user"),))
    with TestClient(app) as client:
        created = client.post("/api/v1/cases", json={**BODY, "heavy": True}, headers=_headers(client, "u1"))
        assert created.status_code == 202
        assert created.json()["job_id"] == jobs.ids[0]
        assert created.json()["status"] == "queued"


def test_guest_can_open_case_but_list_is_empty() -> None:
    _identity, app = _app(build_case_service(), ())
    with TestClient(app) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/v1/cases", json=BODY, headers=headers)
        case_id = created.json()["id"]
        opened = client.get(f"/api/v1/cases/{case_id}", headers=headers)
        assert opened.status_code == 200
        listed = client.get("/api/v1/cases", headers=headers)
        assert listed.json() == []


def test_stranger_cannot_read_and_only_admin_deletes_assignment_case() -> None:
    store = MemoryCaseStore()
    assignments = MemoryAssignments()
    _identity, app = _app(
        build_case_service(store=store, assignments=assignments),
        (("u1", "user"), ("u2", "user"), ("admin", "admin")),
    )
    with TestClient(app) as client:
        owner = _headers(client, "u1")
        stranger = _headers(client, "u2")
        admin = _headers(client, "admin")
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        case_id = created.json()["id"]
        hidden = client.get(f"/api/v1/cases/{case_id}", headers=stranger)
        assert hidden.status_code == 404

        removed = client.delete(f"/api/v1/cases/{case_id}", headers=owner)
        assert removed.status_code == 204

        again = client.post("/api/v1/cases", json=BODY, headers=owner)
        linked = again.json()["id"]
        assignments.linked.add(linked)
        denied = client.delete(f"/api/v1/cases/{linked}", headers=owner)
        assert denied.status_code == 403
        allowed = client.delete(f"/api/v1/cases/{linked}", headers=admin)
        assert allowed.status_code == 204
        assert linked not in store.cases


def test_profile_urban_compare_and_rejected_inputs() -> None:
    _identity, app = _app(build_case_service(), (("u1", "user"), ("u2", "user")))
    with TestClient(app) as client:
        owner = _headers(client, "u1")
        stranger = _headers(client, "u2")
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        case_id = created.json()["id"]
        profile = client.get(f"/api/v1/cases/{case_id}/profile", headers=owner)
        assert profile.status_code == 200
        assert [level["pressure_hpa"] for level in profile.json()["levels"]] == [1000, 850]
        assert client.get(f"/api/v1/cases/{case_id}/profile", headers=stranger).status_code == 404
        urban = client.get(f"/api/v1/cases/{case_id}/urban", headers=owner)
        assert urban.status_code == 200
        assert urban.json() == {
            "case_id": case_id,
            "city_slope": -0.16,
            "ring_slope": -0.09,
            "difference": -0.07,
        }
        heavy = client.post("/api/v1/cases", json={**BODY, "heavy": True}, headers=owner)
        assert client.get(f"/api/v1/cases/{heavy.json()['id']}/profile", headers=owner).status_code == 404
        short = client.post("/api/v1/cases", json={**BODY, "period_end": "2001-01"}, headers=owner)
        assert short.status_code == 422
        assert short.json()["detail"]["code"] == "period_too_short"
        missing = client.post("/api/v1/cases", json={**BODY, "variable_id": "nope"}, headers=owner)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "variable_not_found"
        one = client.post("/api/v1/cases/compare", json={**BODY, "region_ids": ["ukraine_south"]}, headers=owner)
        assert one.status_code == 422
        assert one.json()["detail"]["code"] == "compare_invalid"
        five = client.post(
            "/api/v1/cases/compare",
            json={**BODY, "region_ids": ["ukraine_south", "ukraine_north", "ukraine_south", "ukraine_north", "ukraine_south"]},
            headers=owner,
        )
        assert five.status_code == 422
        pair = client.post(
            "/api/v1/cases/compare",
            json={**BODY, "region_ids": ["ukraine_south", "ukraine_north"]},
            headers=owner,
        )
        assert pair.status_code == 201
        slopes = {item["region_id"]: item["verdict"]["code"] for item in pair.json()["cases"]}
        assert slopes == {"ukraine_south": "strong", "ukraine_north": "strong"}
        assert [item["region_id"] for item in pair.json()["cases"]] == ["ukraine_south", "ukraine_north"]


def test_repeat_uses_cache_until_the_dataset_version_changes() -> None:
    from earthtrend.api.domain.cases.model import CaseSpec
    from earthtrend.api.infrastructure.cases.memory import MemoryAnalysis

    analysis = MemoryAnalysis()
    service = build_case_service(analysis=analysis)

    async def scenario() -> None:
        spec = CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12")
        first = await service.create(spec=spec, owner_id="u1", role="user")
        second = await service.create(spec=spec, owner_id="u1", role="user")
        warm = await service.create(
            spec=CaseSpec("merra2_t2m", "ukraine_south", "2000-01", "2025-12"),
            owner_id="u1",
            role="user",
        )
        assert analysis.calls == 2
        assert first.series is not None and second.series is not None and warm.series is not None
        assert first.series.slope_decade == second.series.slope_decade == -0.21
        assert warm.series.slope_decade == 0.18
        assert warm.series.gam.accelerating is True
        assert first.result_hash == second.result_hash
        analysis.datasets_version = "datasets-v2"
        await service.create(spec=spec, owner_id="u1", role="user")
        assert analysis.calls == 3

    asyncio.run(scenario())

