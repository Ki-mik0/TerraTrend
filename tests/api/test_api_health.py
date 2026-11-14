from __future__ import annotations

from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.analytics import ANALYTICS_VERSION
from earthtrend.api.api.app import create_app
from earthtrend.api.settings import Settings


def test_health_reports_dependencies(client: TestClient[Litestar]) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": True, "analytics": True}
    assert body["analytics_version"] == ANALYTICS_VERSION


def test_live_skips_dependency_checks(client: TestClient[Litestar]) -> None:
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json()["checks"] == {}


def test_ready_is_503_when_database_is_down(settings: Settings) -> None:
    # A directory path cannot be opened as a SQLite file.
    broken = settings.model_copy(update={"db_url": "sqlite+aiosqlite:///.."})
    with TestClient(app=create_app(broken)) as c:
        r = c.get("/api/v1/health/ready")
        assert r.status_code == 503
        assert r.json()["checks"]["database"] is False
        # The overall endpoint still answers 200 and reports the degradation.
        assert c.get("/api/v1/health").json()["status"] == "degraded"


def test_request_id_is_echoed(client: TestClient[Litestar]) -> None:
    r = client.get("/api/v1/health/live", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert client.get("/api/v1/health/live").headers["x-request-id"]


def test_openapi_lists_v1_routes(client: TestClient[Litestar]) -> None:
    r = client.get("/api/v1/schema/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert {"/api/v1/health", "/api/v1/health/ready", "/api/v1/analyze"} <= set(paths)


def test_unknown_route_uses_error_body(client: TestClient[Litestar]) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
    assert set(r.json()) == {"code", "message", "details"}
