import pytest

from earthtrend.api.domain.tiles.model import GridProduct, TileError, TileRequest, parse_period, tile_lonlat


def _request(**overrides) -> TileRequest:
    base = dict(product="trend", z=2, x=1, y=1, variable_id="gldas_sm", period="2000-2024")
    return TileRequest(**{**base, **overrides})


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"product": "rgb"}, "product_invalid"),
        ({"z": 13}, "tile_out_of_range"),
        ({"z": -1}, "tile_out_of_range"),
        ({"x": 4}, "tile_out_of_range"),
        ({"y": -1}, "tile_out_of_range"),
        ({"palette": "jet"}, "palette_invalid"),
        ({"season": "summer"}, "season_invalid"),
        ({"period": "2000"}, "period_invalid"),
        ({"period": "2024-2000"}, "period_invalid"),
        ({"year": 1999}, "year_invalid"),
    ],
)
def test_request_validation(overrides, code) -> None:
    with pytest.raises(TileError) as error:
        _request(**overrides)
    assert error.value.code == code


def test_bounds_and_storage_key() -> None:
    whole = _request(z=0, x=0, y=0)
    west, south, east, north = whole.bounds()
    assert west == -180 and east == 180 and north > 85 and south < -85
    assert tile_lonlat(1, 1, 1) == (0.0, 0.0)
    key = _request(year=2010, significant_only=True).storage_key("v9")
    assert key == "tile/v9/trend/gldas_sm/2000-2024/annual/rdbu/sig/2010/2/1/1.png"
    assert parse_period("1990-2020") == (1990, 2020)


def test_grid_product_rules() -> None:
    grid = GridProduct(
        variable_id="v", period="2000-2024", season="annual", version="1", bbox=(20, 40, 40, 55), resolution=0.5, vmax=1
    )
    assert grid.overlaps((30, 45, 50, 60)) and not grid.overlaps((-10, 0, 0, 10))
    assert grid.has_frame(None) and not grid.has_frame(2010)
    with pytest.raises(TileError):
        GridProduct(variable_id="v", period="2000-2024", season="annual", version="1", bbox=(40, 40, 20, 55), resolution=1, vmax=1)
    with pytest.raises(TileError):
        GridProduct(variable_id="v", period="2000-2024", season="annual", version="1", bbox=(0, 0, 1, 1), resolution=0, vmax=1)
