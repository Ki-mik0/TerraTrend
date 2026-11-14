import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from earthtrend.api.application.tiles.ports import GridArrays
from earthtrend.api.domain.tiles.model import GridProduct, TileError, TileRequest
from earthtrend.api.infrastructure.tiles.grids import SEED_VERSION, FileGridStore
from earthtrend.api.infrastructure.tiles.png_tile_renderer import AI_COLOURS, PillowTileRenderer, pixel_lonlat

# A small grid over 20–40°E, 40–55°N: west half significant and drying, east half not significant.
GRID = GridProduct(
    variable_id="gldas_sm", period="2000-2024", season="annual", version="t1",
    bbox=(20.0, 40.0, 40.0, 55.0), resolution=1.0, vmax=0.04, years=(2010,), file="t1",
)
SLOPE = np.full((15, 20), -0.04, dtype=np.float32)
SIG = np.zeros((15, 20), dtype=np.uint8)
SIG[:, :10] = 1
CLASSES = np.zeros((15, 20), dtype=np.uint8)
CLASSES[:, :10] = 2  # step


def _image(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data))
    assert image.size == (256, 256) and image.mode == "RGBA"
    return np.asarray(image)


def _pixel_of(z, x, y, lon, lat):
    lons, lats = pixel_lonlat(z, x, y)
    row = int(np.argmin(np.abs(lats[:, 0] - lat)))
    col = int(np.argmin(np.abs(lons[0, :] - lon)))
    return row, col


def test_trend_tile_colours_significance_and_outside() -> None:
    request = TileRequest(product="trend", z=3, x=4, y=2, variable_id="gldas_sm", period="2000-2024")
    pixels = _image(PillowTileRenderer().render(request, GRID, GridArrays(SLOPE, SIG, CLASSES)))
    west = pixels[_pixel_of(3, 4, 2, 25, 47)]
    east = pixels[_pixel_of(3, 4, 2, 35, 47)]
    outside = pixels[_pixel_of(3, 4, 2, 10, 47)]  # inside the tile, west of the grid
    assert west[3] == 215 and east[3] == 90  # significant vs faint
    assert west[2] > west[0]  # negative slope is blue on rdbu
    assert outside[3] == 0

    only = TileRequest(product="trend", z=3, x=4, y=2, variable_id="gldas_sm", period="2000-2024", significant_only=True)
    sig_pixels = _image(PillowTileRenderer().render(only, GRID, GridArrays(SLOPE, SIG, CLASSES)))
    assert sig_pixels[_pixel_of(3, 4, 2, 35, 47)][3] == 0


def test_ai_class_and_empty_tiles() -> None:
    request = TileRequest(product="ai_class", z=3, x=4, y=2, variable_id="gldas_sm", period="2000-2024")
    pixels = _image(PillowTileRenderer().render(request, GRID, GridArrays(SLOPE, SIG, CLASSES)))
    assert tuple(pixels[_pixel_of(3, 4, 2, 25, 47)]) == AI_COLOURS["step"]
    assert pixels[_pixel_of(3, 4, 2, 35, 47)][3] == 0  # class none stays transparent
    assert _image(PillowTileRenderer().empty()).max() == 0


async def test_seed_grids_frames_and_lru() -> None:
    store = FileGridStore(Path("does-not-exist"))
    assert await store.version() == SEED_VERSION
    product = await store.find("merra2_t2m", "2000-2024", "annual")
    assert product is not None and product.years[0] == 2000
    assert await store.find("merra2_t2m", "1990-2000", "annual") is None
    assert {item.season for item in await store.products("gldas_sm")} == {"annual", "JJA"}
    trend = await store.arrays(product, None)
    early = await store.arrays(product, 2000)
    late = await store.arrays(product, 2024)
    assert np.mean(late.values) > np.mean(early.values)
    assert await store.arrays(product, None) is trend and store.loads == 3
    for year in range(2001, 2012):
        await store.arrays(product, year)
    assert len(store._arrays) == 8


async def test_file_grid_store_reads_index_and_npz(tmp_path: Path) -> None:
    np.savez(tmp_path / "sm_v2.npz", slope=SLOPE, sig_fdr=SIG, ai_class=CLASSES, ai_step_prob=SIG, anomaly_2010=SLOPE * 2)
    index = {
        "products": [
            {"variable_id": "gldas_sm", "period": "2000-2024", "season": "annual", "version": "v2", "file": "sm_v2",
             "bbox": [20, 40, 40, 55], "resolution": 1, "vmax": 0.04, "years": [2010]},
            {"variable_id": "broken", "period": "x"},
        ]
    }
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    store = FileGridStore(tmp_path)
    assert await store.version() == "v2"
    product = await store.find("gldas_sm", "2000-2024", "annual")
    assert product is not None and len(await store.products()) == 1
    frame = await store.arrays(product, 2010)
    assert float(frame.values[0, 0]) == pytest.approx(-0.08)
    computed = await store.arrays(product, 2005)  # no stored frame: derived from the slope
    assert computed.values.shape == SLOPE.shape

    escaped = GridProduct(**{**product.__dict__, "file": "../outside", "version": "v3"})
    with pytest.raises(TileError):
        await store.arrays(escaped, None)
