import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.api.api.identity.routes import identity_router
from earthtrend.api.api.story.routes import story_router
from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.domain.story.model import Draft, StoryFacts
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.catalog.memory import seed_catalog
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.infrastructure.story.wiring import build_story_service


class LyingNarrator:
    async def write(self, *, language: str, facts: StoryFacts) -> Draft:
        return Draft("Вигадане число 9.99", "model")


@contextmanager
def _app(narrator=None) -> Iterator[tuple[TestClient, dict, dict, dict]]:
    store = MemoryCaseStore()
    cases = build_case_service(store=store)
    stories = build_story_service(cases=store, catalog=seed_catalog(), narrator=narrator or LyingNarrator())
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="u2", username="u2", role="user", password="secret"))
    ready = asyncio.run(
        cases.create(spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"), owner_id="u1", role="user")
    )
    queued = asyncio.run(
        cases.create(
            spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12", heavy=True), owner_id="u1", role="user"
        )
    )
    app = Litestar(route_handlers=[story_router(stories, identity), identity_router(identity)])
    with TestClient(app) as client:
        def login(name: str) -> dict:
            token = client.post("/api/v1/session", json={"username": name, "password": "secret"}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        yield client, login("u1"), login("u2"), {"ready": ready.id, "queued": queued.id}


def test_case_story_uses_facts_and_rejects_invented_numbers() -> None:
    with _app() as (client, owner, _, ids):
        story = client.get(f"/api/v1/cases/{ids['ready']}/story", headers=owner)
        assert story.status_code == 200
        body = story.json()
        assert "9.99" not in body["text"] and body["source"] == "template"
        assert body["warnings"] == ["draft_rejected"]
        assert body["title"] == "Soil moisture · Ukraine south: висихання"
        assert body["pattern"] == "drying" and body["direction"] == "decreasing"
        assert str(body["slope_decade"]) in body["text"]
        assert body["related"][0] == {
            "variable_id": "merra2_t2m",
            "name": "Air temperature",
            "role": "driver",
            "lag_months": 0,
            "partial_r": None,
        }
        assert body["papers"][0]["doi"] and "correlation_not_causation" in body["caveats"]
        assert {"catalog", "datasets", "algorithm", "ruleset"} <= set(body["versions"])

        again = client.get(f"/api/v1/cases/{ids['ready']}/story", headers=owner).json()
        assert again["cached"] is True and again["source"] == "cache" and again["id"] == body["id"]
        english = client.get(f"/api/v1/cases/{ids['ready']}/story?language=en", headers=owner).json()
        assert english["language"] == "en" and "per decade" in english["text"]


def test_case_story_errors() -> None:
    with _app() as (client, owner, stranger, ids):
        hidden = client.get(f"/api/v1/cases/{ids['ready']}/story", headers=stranger)
        assert hidden.status_code == 404 and hidden.json()["detail"]["code"] == "case_not_found"
        waiting = client.get(f"/api/v1/cases/{ids['queued']}/story", headers=owner)
        assert waiting.status_code == 409 and waiting.json()["detail"]["code"] == "data_not_ready"
        assert client.get(f"/api/v1/cases/{ids['ready']}/story?language=fr", headers=owner).status_code == 400
        assert client.get(f"/api/v1/cases/{ids['ready']}/story").status_code == 401


def test_spec_story_and_its_errors() -> None:
    class Honest:
        async def write(self, *, language: str, facts: StoryFacts) -> Draft:
            return Draft(f"Slope {facts.slope_decade} per decade.", "model")

    with _app(Honest()) as (client, owner, _, _ids):
        posted = client.post(
            "/api/v1/story", json={"variable_id": "gldas_sm", "region_id": "ukraine_south", "language": "en"}, headers=owner
        )
        assert posted.status_code == 201
        body = posted.json()
        assert body["source"] == "model" and body["case_id"] is None and body["warnings"] == []

        for payload, status, code in (
            ({"variable_id": "nope", "region_id": "ukraine_south"}, 404, "variable_not_found"),
            ({"variable_id": "gldas_sm", "region_id": "mars"}, 404, "region_not_found"),
            ({"variable_id": "merra2_t2m", "region_id": "ukraine_north"}, 409, "data_not_ready"),
        ):
            response = client.post("/api/v1/story", json=payload, headers=owner)
            assert response.status_code == status and response.json()["detail"]["code"] == code
        bad = {"variable_id": "gldas_sm", "region_id": "ukraine_south", "language": "fr"}
        assert client.post("/api/v1/story", json=bad, headers=owner).status_code == 400
        assert client.post("/api/v1/story", json={"variable_id": "", "region_id": "x"}, headers=owner).status_code == 400
