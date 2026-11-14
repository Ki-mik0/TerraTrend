from __future__ import annotations

from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.api.main import create_app


def test_health_reports_analytics(client: TestClient[Litestar]) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "analytics" in body["checks"]


def test_live_skips_dependency_checks(client: TestClient[Litestar]) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["checks"] == {}


def test_ready_answers(client: TestClient[Litestar]) -> None:
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}
    assert "status" in response.json()


def test_analyze_route_is_on_the_product_app() -> None:
    with TestClient(app=create_app()) as client:
        missing = client.post("/api/v1/analyze", json={"series": {"meta": {}, "dates": [], "values": []}})
        assert missing.status_code in {400, 422}
