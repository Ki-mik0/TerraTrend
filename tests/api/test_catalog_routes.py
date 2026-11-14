import asyncio

import pytest
from litestar.testing import TestClient

from earthtrend.api.api.catalog.schemas import CmrResponse, PassportDetailResponse, RegionResponse
from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.infrastructure.catalog.memory import MemorySearch, seed_catalog
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app


def test_unknown_variable_is_not_found() -> None:
    app = create_app(catalog=seed_catalog())
    with TestClient(app) as client:
        response = client.get("/api/v1/variables/missing")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "variable_not_found"


def test_text_search_and_m3_synonym() -> None:
    plain = seed_catalog(MemorySearch(enabled=False))
    semantic = seed_catalog(MemorySearch(enabled=True))
    with TestClient(create_app(catalog=plain)) as client:
        found = client.get("/api/v1/variables", params={"q": "temperature"})
        assert [item["id"] for item in found.json()] == ["merra2_t2m"]
        missed = client.get("/api/v1/variables", params={"q": "посуха"})
        assert missed.json() == []
    with TestClient(create_app(catalog=semantic)) as client:
        found = client.get("/api/v1/variables", params={"q": "посуха"})
        assert [item["id"] for item in found.json()] == ["gldas_sm"]


def test_custom_region_and_potential() -> None:
    app = create_app(catalog=seed_catalog())
    with TestClient(app) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        created = client.post(
            "/api/v1/regions/custom",
            json={"name": "My field", "bbox": [30.0, 46.0, 32.0, 48.0]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "registered"
        assert body["id"].startswith("reg_")
        hints = client.get("/api/v1/regions/ukraine_south/potential")
        assert hints.status_code == 200
        assert hints.json()[0]["variable_id"] == "gldas_sm"
        assert hints.json()[0]["expected_sign"] == -1


def test_reload_catalog_is_admin_only() -> None:
    catalog = seed_catalog()
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="admin", username="admin", role="admin", password="secret"))
    app = create_app(catalog=catalog, identity=identity)
    with TestClient(app) as client:
        user = client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        admin = client.post("/api/v1/session", json={"username": "admin", "password": "secret"}).json()["token"]
        denied = client.post("/api/v1/admin/reload-catalog", headers={"Authorization": f"Bearer {user}"})
        assert denied.status_code == 403
        allowed = client.post("/api/v1/admin/reload-catalog", headers={"Authorization": f"Bearer {admin}"})
        assert allowed.status_code == 201
        assert allowed.json()["generation"] == 2


@pytest.mark.asyncio
async def test_completed_case_records_potential_feedback() -> None:
    catalog = seed_catalog()
    cases = build_case_service(feedback=catalog)
    spec = CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12")
    case = await cases.create(spec=spec, owner_id="u1", role="user")
    assert len(catalog.feedback) == 1
    assert catalog.feedback[0].case_id == case.id
    assert catalog.feedback[0].variable_id == "gldas_sm"
    assert catalog.feedback[0].actual_code == "strong"


def test_passport_body_theme_filter_and_region_shapes() -> None:
    app = create_app(catalog=seed_catalog())
    polygon = {
        "type": "Polygon",
        "coordinates": [[[30.0, 46.0], [32.0, 46.0], [32.0, 48.0], [30.0, 46.0]]],
    }
    with TestClient(app) as client:
        token = client.post("/api/v1/session/guest").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        denied = client.post("/api/v1/regions/custom", json={"name": "Field", "bbox": [30, 46, 32, 48]})
        assert denied.status_code == 401
        assert denied.json()["detail"]["code"] == "invalid_token"
        snow = client.get("/api/v1/variables", params={"theme": "cryosphere", "domain": "snow"})
        assert snow.status_code == 200
        assert {item["id"] for item in snow.json()} == {"modis_snow", "gldas_swe", "nsidc_ice"}
        body = client.get("/api/v1/variables/merra2_t2m")
        assert body.status_code == 200
        passport = PassportDetailResponse.model_validate(body.json())
        assert passport.theme == "atmosphere"
        assert passport.domain == "temperature"
        assert passport.level == "curated"
        assert passport.witnesses == ["airs_t", "modis_lst"]
        assert passport.doi.startswith("10.5067/")
        assert any(link.direction == "driver" for link in passport.links)
        assert any(event.instrument == "merra2" and event.year == 2015 for event in passport.events)
        missing = client.post("/api/v1/regions/custom", json={"name": "Nowhere"}, headers=headers)
        assert missing.status_code == 422
        assert missing.json()["detail"]["code"] == "region_invalid"
        broken = client.post(
            "/api/v1/regions/custom",
            json={"name": "Broken", "geometry": {"type": "Polygon", "coordinates": [[[1, 2]]]}},
            headers=headers,
        )
        assert broken.status_code == 422
        drawn = client.post("/api/v1/regions/custom", json={"name": "Plot", "geometry": polygon}, headers=headers)
        assert drawn.status_code == 201
        region = RegionResponse.model_validate(drawn.json())
        assert region.geometry["type"] == "Polygon"
        assert region.bbox[0] == 30.0 and region.bbox[2] == 32.0
        point = client.post(
            "/api/v1/regions/custom",
            json={"name": "Well", "point": [30.5, 47.0], "radius_km": 10},
            headers=headers,
        )
        assert point.status_code == 201
        well = RegionResponse.model_validate(point.json())
        assert well.geometry["type"] == "Point"
        assert well.geometry["radius_km"] == 10
        city = RegionResponse.model_validate(client.get("/api/v1/regions/kyiv").json())
        assert city.kind == "city" and city.ring is not None and len(city.ring) == 4


def test_cmr_registers_once_and_reload_is_admin_only() -> None:
    catalog = seed_catalog()
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="admin", username="admin", role="admin", password="secret"))
    app = create_app(catalog=catalog, identity=identity)
    with TestClient(app) as client:
        guest = client.post("/api/v1/session/guest").json()["token"]
        admin = client.post("/api/v1/session", json={"username": "admin", "password": "secret"}).json()["token"]
        no_token = client.post("/api/v1/variables/cmr", json={"query": "SMAP L-band 2015"})
        assert no_token.status_code == 401
        ready = client.post(
            "/api/v1/variables/cmr",
            json={"query": "gldas_sm"},
            headers={"Authorization": f"Bearer {guest}"},
        )
        assert ready.status_code == 200
        assert CmrResponse.model_validate(ready.json()) == CmrResponse(id="gldas_sm", job_id=None)
        created = client.post(
            "/api/v1/variables/cmr",
            json={"query": "SMAP L-band 2015"},
            headers={"Authorization": f"Bearer {guest}"},
        )
        assert created.status_code == 202
        first = CmrResponse.model_validate(created.json())
        assert first.job_id == "cmr_1" and first.id == "smap_l_band_2015"
        again = client.post(
            "/api/v1/variables/cmr",
            json={"query": "SMAP L-band 2015"},
            headers={"Authorization": f"Bearer {guest}"},
        )
        assert again.status_code == 200
        assert CmrResponse.model_validate(again.json()).id == first.id
        assert sum(item.level == "cmr" for item in catalog.passports.values()) == 1
        listed = client.get("/api/v1/variables", params={"level": "cmr"})
        assert [item["id"] for item in listed.json()] == ["smap_l_band_2015"]
        field = client.post(
            "/api/v1/regions/custom",
            json={"name": "Field", "bbox": [30.0, 46.0, 32.0, 48.0]},
            headers={"Authorization": f"Bearer {guest}"},
        )
        region_id = field.json()["id"]
        reloaded = client.post("/api/v1/admin/reload-catalog", headers={"Authorization": f"Bearer {admin}"})
        assert reloaded.status_code == 201
        assert client.get(f"/api/v1/regions/{region_id}").status_code == 404
        assert client.get("/api/v1/variables/smap_l_band_2015").status_code == 200
