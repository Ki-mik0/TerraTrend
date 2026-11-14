import asyncio

from litestar.testing import TestClient

from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.infrastructure.shared.metrics import CACHE_HITS, counter_value
from earthtrend.api.main import create_app


def _app():
    identity = build_identity_service()
    for user_id, role in (("root", "admin"), ("u1", "user")):
        asyncio.run(identity.add_user(user_id=user_id, username=user_id, role=role, password="secret"))
    return identity, create_app(identity=identity)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    token = client.post("/api/v1/session", json={"username": username, "password": "secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_only_admin_manages_the_cache() -> None:
    _, app = _app()
    with TestClient(app) as client:
        user = _headers(client, "u1")
        assert client.get("/api/v1/admin/cache", headers=user).status_code == 403
        assert client.post("/api/v1/admin/warm-cache", headers=user).status_code == 403
        assert client.delete("/api/v1/admin/cache", params={"family": "all"}, headers=user).status_code == 403
        assert client.get("/api/v1/admin/cache").status_code == 401


def test_warm_then_hit_then_clear_with_audit() -> None:
    identity, app = _app()
    with TestClient(app) as client:
        admin = _headers(client, "root")
        warmed = client.post("/api/v1/admin/warm-cache", headers=admin)
        assert warmed.status_code == 200
        body = warmed.json()
        assert body["failed"] == {}
        assert body["warmed"] == {"radar": 8, "education": 6, "tiles": 6 * 21}

        hits_before = counter_value(CACHE_HITS, family="radar")
        assert client.get("/api/v1/radar", params={"feed": "stable"}).status_code == 200
        assert counter_value(CACHE_HITS, family="radar") > hits_before
        tile = client.get("/api/v1/tiles/trend/1/0/0.png", params={"variable_id": "gldas_sm", "period": "2000-2024"})
        assert tile.headers["x-tile-cache"] == "hit"

        stats = client.get("/api/v1/admin/cache", headers=admin).json()
        assert stats["backend"] == "memory" and stats["reachable"] is True
        assert stats["families"]["radar"]["hits"] >= 1 and stats["families"]["radar"]["hit_ratio"] is not None

        cleared = client.delete("/api/v1/admin/cache", params={"family": "radar"}, headers=admin).json()
        assert cleared["family"] == "radar" and cleared["removed"] >= 8
        everything = client.delete("/api/v1/admin/cache", params={"family": "all"}, headers=admin).json()
        assert everything["removed"] >= 6 * 21  # tiles on disk plus the lesson pages
        again = client.get("/api/v1/tiles/trend/1/0/0.png", params={"variable_id": "gldas_sm", "period": "2000-2024"})
        assert again.headers["x-tile-cache"] == "miss"

        unknown = client.delete("/api/v1/admin/cache", params={"family": "sessions"}, headers=admin)
        assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "family_unknown"

    actions = [(item.action, item.subject_id) for item in identity.audit]
    assert actions == [("warm_cache", "all"), ("clear_cache", "radar"), ("clear_cache", "all")]


def test_metrics_endpoint_exposes_http_cache_and_tile_counters() -> None:
    with TestClient(create_app()) as client:
        client.get("/api/v1/radar")
        client.get("/api/v1/tiles/trend/0/0/0.png", params={"variable_id": "gldas_sm", "period": "2000-2024"})
        text = client.get("/metrics").text
        assert "http_requests_total" in text and "http_request_duration_seconds" in text
        assert 'cache_misses_total{family="radar"}' in text
        assert "tile_requests_total" in text and "tile_render_seconds" in text
        assert 'path="/health' not in text
