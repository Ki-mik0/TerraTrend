from litestar.testing import TestClient

from earthtrend.api.infrastructure.radar.memory import seed_radar
from earthtrend.api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app(radar=seed_radar()))


def test_strongest_page_has_metadata_label_and_sorted_cards() -> None:
    with _client() as client:
        response = client.get("/api/v1/radar", params={"feed": "strongest"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4 and body["page"] == 1 and body["data_version"] == "seed-1"
        assert "FDR" in body["label"]
        cards = body["items"]
        assert {item["feed"] for item in cards} == {"strongest"}
        assert [item["score"] for item in cards] == sorted((item["score"] for item in cards), reverse=True)
        assert cards[0]["case_url"] == f"/api/v1/cases/{cards[0]['case_id']}"
        assert {"season", "novelty", "years_to_detect", "area_km2"} <= set(cards[0])
        english = client.get("/api/v1/radar", params={"feed": "strongest", "lang": "en"}).json()
        assert english["label"].startswith("Statistical candidates")


def test_filters_and_pages_do_not_repeat() -> None:
    with _client() as client:
        south = client.get("/api/v1/radar", params={"feed": "strongest", "region_id": "ukraine_south"}).json()
        assert [item["region_id"] for item in south["items"]] == ["ukraine_south"]
        summer = client.get("/api/v1/radar", params={"feed": "almost", "season": "JJA"}).json()
        assert summer["items"] and {item["season"] for item in summer["items"]} == {"JJA"}
        assert all(item["years_to_detect"] <= 10 for item in summer["items"])
        first = client.get("/api/v1/radar", params={"feed": "strongest", "page": 1, "page_size": 2}).json()
        second = client.get("/api/v1/radar", params={"feed": "strongest", "page": 2, "page_size": 2}).json()
        assert not {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]}
        assert first["total"] == second["total"] == 4


def test_invalid_queries_are_rejected() -> None:
    with _client() as client:
        for params, code in (
            ({"feed": "invented"}, "feed_invalid"),
            ({"page": 0}, "page_invalid"),
            ({"page_size": 500}, "page_invalid"),
            ({"season": "winter"}, "season_invalid"),
        ):
            response = client.get("/api/v1/radar", params=params)
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == code
        assert client.get("/api/v1/radar/typology", params={"season": "winter"}).status_code == 422


def test_typology_filters_by_variables() -> None:
    with _client() as client:
        everything = client.get("/api/v1/radar/typology").json()
        assert everything["data_version"] == "seed-1" and len(everything["clusters"]) == 3
        dry = client.get("/api/v1/radar/typology", params={"variables": "merra2_t2m, gldas_sm"}).json()
        assert [item["pattern"] for item in dry["clusters"]] == ["warmer_drier_browner"]
        assert dry["clusters"][0]["signs"]["gldas_sm"] == -1
        summer = client.get("/api/v1/radar/typology", params={"season": "JJA"}).json()
        assert [item["id"] for item in summer["clusters"]] == ["typ_warmer_drier_browner"]


def test_etag_answers_not_modified() -> None:
    with _client() as client:
        first = client.get("/api/v1/radar", params={"feed": "stable"})
        etag = first.headers["etag"]
        assert first.headers["cache-control"] == "public, max-age=300"
        cached = client.get("/api/v1/radar", params={"feed": "stable"}, headers={"If-None-Match": etag})
        assert cached.status_code == 304 and cached.content == b""
        other = client.get("/api/v1/radar", params={"feed": "almost"}, headers={"If-None-Match": etag})
        assert other.status_code == 200
        typology = client.get("/api/v1/radar/typology")
        repeat = client.get("/api/v1/radar/typology", headers={"If-None-Match": typology.headers["etag"]})
        assert repeat.status_code == 304
