from litestar.testing import TestClient

from earthtrend.api.main import create_app

QUERY = {"variable_id": "gldas_sm", "period": "2000-2024"}


def test_tile_png_is_rendered_once_then_served_and_revalidated() -> None:
    with TestClient(create_app()) as client:
        first = client.get("/api/v1/tiles/trend/1/1/0.png", params=QUERY)
        assert first.status_code == 200 and first.headers["content-type"] == "image/png"
        assert first.content.startswith(b"\x89PNG") and first.headers["x-tile-cache"] == "miss"
        assert first.headers["cache-control"] == "public, max-age=86400, immutable"
        second = client.get("/api/v1/tiles/trend/1/1/0.png", params=QUERY)
        assert second.headers["x-tile-cache"] == "hit" and second.content == first.content
        revalidated = client.get(
            "/api/v1/tiles/trend/1/1/0.png", params=QUERY, headers={"If-None-Match": first.headers["etag"]}
        )
        assert revalidated.status_code == 304 and revalidated.content == b""
        frame = client.get("/api/v1/tiles/trend/1/1/0.png", params={**QUERY, "year": 2010})
        assert frame.status_code == 200 and frame.headers["etag"] != first.headers["etag"]
        ai = client.get("/api/v1/tiles/ai_class/0/0/0.png", params={**QUERY, "season": "JJA", "palette": "cividis"})
        assert ai.status_code == 200


def test_tile_errors() -> None:
    with TestClient(create_app()) as client:
        cases = [
            ("/api/v1/tiles/trend/1/5/0.png", QUERY, 422, "tile_out_of_range"),
            ("/api/v1/tiles/trend/1/1/0.png", {**QUERY, "palette": "jet"}, 422, "palette_invalid"),
            ("/api/v1/tiles/rgb/1/1/0.png", QUERY, 422, "product_invalid"),
            ("/api/v1/tiles/trend/1/1/0.png", {**QUERY, "variable_id": "made_up"}, 404, "variable_not_found"),
            ("/api/v1/tiles/trend/1/1/0.png", {**QUERY, "variable_id": "grace_tws"}, 404, "grid_not_found"),
            ("/api/v1/tiles/trend/1/1/0.png", {**QUERY, "period": "1990-2000"}, 404, "grid_not_found"),
            ("/api/v1/tiles/trend/1/1/0.jpg", QUERY, 404, "tile_not_found"),
        ]
        for path, params, status, code in cases:
            response = client.get(path, params=params)
            assert response.status_code == status, path
            assert response.json()["detail"]["code"] == code


def test_tile_products_list() -> None:
    with TestClient(create_app()) as client:
        products = client.get("/api/v1/tiles/products", params={"variable_id": "merra2_t2m"}).json()
        assert {item["season"] for item in products} == {"annual", "JJA"}
        assert products[0]["years"][0] == 2000 and "trend" in products[0]["products"]
        assert products[0]["tile_url"].startswith("/api/v1/tiles/{product}/{z}/{x}/{y}.png?variable_id=merra2_t2m")
        assert len(client.get("/api/v1/tiles/products").json()) == 6


def test_computed_grid_has_finite_vmax_new_version_and_renders() -> None:
    dates = [f"{2007 + month // 12}-{month % 12 + 1:02d}-01" for month in range(144)]
    body = {
        "variable_id": "merra2_t2m", "period": "2007-2018", "season": "annual", "dates": dates,
        "lat": [48, 50], "lon": [30, 32], "values": [[[0.2 + 0.001 * month, 0.3], [0.25, 0.28 - 0.002 * month]] for month in range(len(dates))],
    }
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/tiles/products", json=body)
        assert created.status_code == 201
        grid = created.json()
        assert grid["vmax"] > 0 and grid["data_version"].count("-") >= 1
        assert grid["bbox"][0] < 30 < 32 < grid["bbox"][2]
        listed = client.get("/api/v1/tiles/products", params={"variable_id": "merra2_t2m"}).json()
        assert {item["period"] for item in listed} == {"2007-2018"}  # a real grid replaces the seed
        tile = client.get("/api/v1/tiles/trend/3/4/2.png", params={"variable_id": "merra2_t2m", "period": "2007-2018"})
        assert tile.status_code == 200
        again = client.post("/api/v1/tiles/products", json={**body, "values": [[[0.2 - 0.003 * month, 0.3 + 0.002 * month], [0.25, 0.28]] for month in range(len(dates))]})
        assert again.json()["data_version"] != grid["data_version"]
