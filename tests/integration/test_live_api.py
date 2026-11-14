"""HTTP checks against a running API. Skipped unless API_URL is set."""

from __future__ import annotations

import os
import time

import httpx
import pytest

API_URL = os.environ.get("API_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not API_URL, reason="API_URL is not set")


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            probe = httpx.get(f"{API_URL}/api/v1/radar", params={"feed": "strongest"}, timeout=2)
            if probe.status_code == 200:
                break
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.5)
    else:
        pytest.fail(f"API at {API_URL} did not become ready: {last_error}")
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        yield client


def _guest(api: httpx.Client) -> dict[str, str]:
    token = api.post("/api/v1/session/guest").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_and_read_case(api: httpx.Client) -> None:
    headers = _guest(api)
    created = api.post(
        "/api/v1/cases",
        json={
            "variable_id": "gldas_sm",
            "region_id": "ukraine_south",
            "period_start": "2000-01",
            "period_end": "2025-12",
        },
        headers=headers,
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    opened = api.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert opened.status_code == 200
    assert opened.json()["verdict"]["code"] == "strong"


def test_radar_feed_is_available(api: httpx.Client) -> None:
    response = api.get("/api/v1/radar", params={"feed": "strongest"})
    assert response.status_code == 200
    assert response.json()[0]["case_url"].startswith("/api/v1/cases/")


def test_stranger_cannot_read_the_case(api: httpx.Client) -> None:
    owner = _guest(api)
    created = api.post(
        "/api/v1/cases",
        json={
            "variable_id": "gldas_sm",
            "region_id": "ukraine_south",
            "period_start": "2000-01",
            "period_end": "2025-12",
        },
        headers=owner,
    )
    case_id = created.json()["id"]
    hidden = api.get(f"/api/v1/cases/{case_id}", headers=_guest(api))
    assert hidden.status_code == 404
