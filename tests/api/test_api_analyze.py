"""Thin slice: ``POST /api/v1/analyze`` -> ``analyze_series`` -> ``TrendResult``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.analytics import (
    AnalysisOptions,
    RegionalSeries,
    TrendResult,
    analyze_series,
)
from earthtrend.api.api.app import create_app
from earthtrend.api.domain.shared.errors import AnalyticsTimeout
from earthtrend.api.settings import Settings

SeriesFactory = Callable[..., dict[str, Any]]


URL = "/api/v1/analyze"


def test_returns_trend_result_matching_analytics(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    series = make_series()
    r = client.post(URL, json={"series": series})
    assert r.status_code == 200

    got = TrendResult.model_validate(r.json())  # the response is the analytics contract
    expected = analyze_series(RegionalSeries.model_validate(series), AnalysisOptions())
    assert got.verdict == expected.verdict
    assert got.direction == "increasing"
    assert got.primary_slope_per_decade is not None
    assert abs(got.primary_slope_per_decade - expected.primary_slope_per_decade) < 1e-9
    assert got.verdict.code in {"proven", "strong", "likely"}
    assert len(got.series_out.dates) == 30 * 12


def test_options_are_passed_through(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    body = {"series": make_series(), "options": {"season": "JJA", "period": [2000, 2020]}}
    r = client.post(URL, json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["options"]["season"] == "JJA"
    assert out["options"]["period"] == [2000, 2020]
    assert out["n_used"] == 21


def test_flat_series_gives_no_evidence(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    r = client.post(URL, json={"series": make_series(slope_per_decade=0.0, seed=7)})
    assert r.status_code == 200
    assert r.json()["verdict"]["code"] in {"no_evidence", "suspicious"}


def _error(r: Any, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == code
    return body


def test_mismatched_lengths_are_rejected(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    series = make_series()
    series["values"] = series["values"][:-1]
    body = _error(client.post(URL, json={"series": series}), 422, "invalid_request")
    assert body["details"]["errors"]


def test_unknown_field_is_rejected(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    r = client.post(URL, json={"series": make_series(), "extra": 1})
    _error(r, 422, "invalid_request")


def test_period_outside_series_is_a_domain_error(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    body = {"series": make_series(), "options": {"period": [1900, 1950]}}
    out = _error(client.post(URL, json=body), 422, "invalid_series")
    assert out["details"]["series_years"] == [1995, 2024]


def test_empty_series_is_a_domain_error(
    client: TestClient[Litestar], make_series: SeriesFactory
) -> None:
    series = make_series()
    series["dates"], series["values"] = [], []
    _error(client.post(URL, json={"series": series}), 422, "invalid_series")


class _SlowAnalytics:
    version = "fake"

    async def analyze_series(self, series: RegionalSeries, options: AnalysisOptions) -> TrendResult:
        raise AnalyticsTimeout("too slow", timeout_s=0.1)

    async def ping(self) -> bool:
        return True


class _BrokenAnalytics(_SlowAnalytics):
    async def analyze_series(self, series: RegionalSeries, options: AnalysisOptions) -> TrendResult:
        raise RuntimeError("secret stack detail")


def test_analytics_timeout_maps_to_504(settings: Settings, make_series: SeriesFactory) -> None:
    with TestClient(app=create_app(settings, analytics=_SlowAnalytics())) as c:
        body = _error(c.post(URL, json={"series": make_series()}), 504, "analytics_timeout")
        assert body["details"] == {"timeout_s": 0.1}


def test_unexpected_failure_hides_internals(settings: Settings, make_series: SeriesFactory) -> None:
    with TestClient(app=create_app(settings, analytics=_BrokenAnalytics())) as c:
        r = c.post(URL, json={"series": make_series()})
        body = _error(r, 500, "internal_error")
        assert "secret" not in r.text
        assert body["details"] == {}
