"""Build the map trend grids from real NASA POWER data and publish them where the API reads them.

    python scripts/grid_scan.py                 # download (resumable) + analyse + publish
    python scripts/grid_scan.py --analyse-only  # rebuild grids from the downloaded cache
    python scripts/grid_scan.py --params T2M    # only some POWER parameters

NASA POWER serves MERRA-2 based monthly fields with no key. Its regional endpoint returns one
parameter for a box of at most 10 x 10 degrees at the native 0.5 x 0.625 degree grid, so the globe is
648 boxes per parameter. Each box is averaged to 1 degree cells and cached under
`STORAGE_ROOT/grids/power-raw/<PARAM>/<lat>_<lon>.npy`, so an interrupted download resumes.

For every POWER parameter and season (annual, DJF, MAM, JJA, SON) the analytics `analyze_grid` runs
per cell (Sen slope + Mann-Kendall + OLS-AR1, FDR across the globe), yearly anomaly frames are added
for the timelapse, and `grids/index.json` lists one product per catalog variable that maps to that
parameter (`POWER_PARAMETERS`, the same mapping cases use). The running API picks the new index up
without a restart.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earthtrend.analytics import analyze_grid, config  # noqa: E402
from earthtrend.api.infrastructure.cases.sources import POWER_PARAMETERS  # noqa: E402

URL = "https://power.larc.nasa.gov/api/temporal/monthly/regional"
FIRST_YEAR = 1991
BASELINE = (1991, 2020)
BOX = 10
SEASONS = ("annual", "DJF", "MAM", "JJA", "SON")
LAT = np.arange(89.5, -90, -1.0)  # rows north -> south
LON = np.arange(-179.5, 180, 1.0)  # columns west -> east


def storage() -> Path:
    return Path(os.environ.get("STORAGE_ROOT", ROOT / "data" / "storage")) / "grids"


def boxes() -> list[tuple[int, int]]:
    return [(lat0, lon0) for lat0 in range(-90, 90, BOX) for lon0 in range(-180, 180, BOX)]


def box_cells(features: list[dict], parameter: str, lat0: int, lon0: int, months: list[str]) -> np.ndarray:
    """Average the native POWER points of one box into its 10 x 10 one-degree cells (south -> north)."""
    total = np.zeros((len(months), BOX, BOX))
    count = np.zeros((len(months), BOX, BOX))
    for feature in features:
        lon, lat = feature["geometry"]["coordinates"][:2]
        i, j = int(np.floor(lat - lat0)), int(np.floor(lon - lon0))
        if lat0 + BOX == 90 and i == BOX:
            i = BOX - 1  # the pole row belongs to the last cell
        if lon0 + BOX == 180 and j == BOX:
            j = BOX - 1
        if not (0 <= i < BOX and 0 <= j < BOX):
            continue  # an edge point shared with the neighbouring box
        values = feature["properties"]["parameter"][parameter]
        series = np.array([values.get(key, -999.0) for key in months], dtype=float)
        ok = series > -990
        total[ok, i, j] += series[ok]
        count[ok, i, j] += 1
    with np.errstate(invalid="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan).astype(np.float32)


async def download(parameters: list[str], last_year: int, workers: int) -> None:
    months = [f"{year}{month:02d}" for year in range(FIRST_YEAR, last_year + 1) for month in range(1, 13)]
    todo = [
        (parameter, lat0, lon0)
        for parameter in parameters
        for lat0, lon0 in boxes()
        if not (storage() / "power-raw" / parameter / f"{lat0}_{lon0}.npy").exists()
    ]
    total = len(todo)
    print(f"{total} boxes to download ({len(parameters)} parameters x {len(boxes())} boxes, cached ones skipped)", flush=True)
    if not total:
        return
    gate = asyncio.Semaphore(workers)
    done = 0
    started = time.monotonic()

    async with httpx.AsyncClient(timeout=180.0) as client:

        async def one(parameter: str, lat0: int, lon0: int) -> None:
            nonlocal done
            params = {
                "parameters": parameter,
                "community": "AG",
                "latitude-min": lat0,
                "latitude-max": lat0 + BOX,
                "longitude-min": lon0,
                "longitude-max": lon0 + BOX,
                "start": FIRST_YEAR,
                "end": last_year,
                "format": "JSON",
            }
            async with gate:
                for attempt in range(6):
                    try:
                        response = await client.get(URL, params=params)
                        if response.status_code in (429, 500, 502, 503, 504):
                            raise httpx.HTTPStatusError("retry", request=response.request, response=response)
                        response.raise_for_status()
                        features = response.json()["features"]
                        break
                    except (httpx.HTTPError, KeyError, ValueError) as error:
                        if attempt == 5:
                            print(f"  FAILED {parameter} {lat0},{lon0}: {error}", flush=True)
                            return
                        await asyncio.sleep(2 ** attempt)
            cells = await asyncio.to_thread(box_cells, features, parameter, lat0, lon0, months)
            path = storage() / "power-raw" / parameter / f"{lat0}_{lon0}.npy"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp.npy")
            np.save(tmp, cells)
            tmp.replace(path)
            done += 1
            if done % 25 == 0 or done == total:
                rate = done / (time.monotonic() - started)
                print(f"  {done}/{total} boxes, ~{(total - done) / rate / 60:.0f} min left", flush=True)

        await asyncio.gather(*(one(*item) for item in todo))


def assemble(parameter: str, n_months: int) -> np.ndarray | None:
    """Global (time, 180, 360) cube from the cached boxes; None while boxes are missing."""
    cube = np.full((n_months, LAT.size, LON.size), np.nan, dtype=np.float32)
    for lat0, lon0 in boxes():
        path = storage() / "power-raw" / parameter / f"{lat0}_{lon0}.npy"
        if not path.exists():
            return None
        cells = np.load(path)
        if cells.shape[0] != n_months:
            return None
        rows = 89 - lat0 - np.arange(BOX)  # box rows run south -> north
        cols = lon0 + 180 + np.arange(BOX)
        cube[:, rows[:, None], cols[None, :]] = cells
    return cube


def frames(cube: np.ndarray, dates: list[date], season: str, baseline: tuple[int, int] = BASELINE) -> dict[int, np.ndarray]:
    """Mean anomaly (vs the baseline monthly climatology) of each year or season, per cell."""
    years = np.array([d.year for d in dates])
    months = np.array([d.month for d in dates])
    base = (years >= baseline[0]) & (years <= baseline[1])
    anomaly = np.empty_like(cube)
    for month in range(1, 13):
        rows = months == month
        with np.errstate(invalid="ignore"), _quiet():
            anomaly[rows] = cube[rows] - np.nanmean(cube[rows & base], axis=0)
    if season == "annual":
        keep, label, need = np.ones(len(dates), bool), years, 10
    else:
        keep = np.isin(months, config.SEASON_MONTHS[season])
        label, need = years + ((months == 12) & (season == "DJF")), 2
    out: dict[int, np.ndarray] = {}
    for year in sorted(set(label[keep])):
        rows = keep & (label == year)
        if rows.sum() < need:
            continue
        block = anomaly[rows]
        enough = np.isfinite(block).sum(axis=0) >= need
        with _quiet():
            out[int(year)] = np.where(enough, np.nanmean(block, axis=0), np.nan).astype(np.float32)
    return out


class _quiet:
    def __enter__(self):
        import warnings

        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore", RuntimeWarning)

    def __exit__(self, *exc):
        self._w.__exit__(*exc)


def grid_products(
    cube: np.ndarray,
    dates: list[date],
    *,
    file_stem: str,
    variables: list[str],
    units: str,
    source: str,
    version: str,
    baseline: tuple[int, int] = BASELINE,
) -> list[dict]:
    """Analyse one global monthly cube for every season, save the grids and return their index rows."""
    period = f"{dates[0].year}-{dates[-1].year}"
    rows: list[dict] = []
    for season in SEASONS:
        started = time.monotonic()
        product = analyze_grid(cube.astype(np.float64), LAT, LON, dates, baseline=baseline, season=season, ai=season == "annual")
        slope = product.fields.slope.astype(np.float32)
        finite = np.abs(slope[np.isfinite(slope)])
        if not finite.size:
            print(f"  {season}: no valid cells", flush=True)
            continue
        vmax = float(np.percentile(finite, 98)) or float(finite.max()) or 1.0
        yearly = frames(cube, dates, season, baseline)
        spread = np.concatenate([np.abs(f[np.isfinite(f)]) for f in yearly.values()]) if yearly else np.array([1.0])
        frame_vmax = float(np.percentile(spread, 98)) if spread.size else 1.0
        frame_vmax = frame_vmax if np.isfinite(frame_vmax) and frame_vmax > 0 else 1.0
        shape = slope.shape
        ai = product.ai_class if product.ai_class is not None else np.zeros(shape)
        step = product.ai_step_prob if product.ai_step_prob is not None else np.zeros(shape)
        file_name = f"{file_stem}-{period}-{season}"
        np.savez_compressed(
            storage() / f"{file_name}.npz",
            slope=slope,
            sig_fdr=product.sig_fdr.astype(np.uint8),
            ai_class=np.clip(np.nan_to_num(ai, nan=0), 0, 4).astype(np.uint8),
            ai_step_prob=np.nan_to_num(step, nan=0).astype(np.float32),
            **{f"anomaly_{year}": frame for year, frame in yearly.items()},
        )
        summary = product.summary
        print(
            f"  {season}: {summary.n_cells_valid} cells, {summary.n_cells_significant} significant (FDR), "
            f"vmax {vmax:.3g} {units}/decade, {len(yearly)} frames, {time.monotonic() - started:.0f}s",
            flush=True,
        )
        for variable_id in variables:
            rows.append(
                {
                    "variable_id": variable_id,
                    "period": period,
                    "season": season,
                    "version": version,
                    "file": file_name,
                    "bbox": [-180.0, -90.0, 180.0, 90.0],
                    "resolution": 1.0,
                    "vmax": vmax,
                    "frame_vmax": frame_vmax,
                    "years": sorted(yearly),
                    "source": f"{source}, monthly {period}, 1 degree",
                }
            )
    return rows


def analyse(parameters: list[str], last_year: int) -> list[dict]:
    dates = [date(year, month, 1) for year in range(FIRST_YEAR, last_year + 1) for month in range(1, 13)]
    version = f"power-grid-{datetime.now(UTC):%Y-%m-%d}"
    rows: list[dict] = []
    for parameter in parameters:
        cube = assemble(parameter, len(dates))
        if cube is None:
            print(f"{parameter}: download incomplete, skipped", flush=True)
            continue
        variables = sorted(v for v, (p, _, _) in POWER_PARAMETERS.items() if p == parameter)
        units = next(u for p, u, _ in POWER_PARAMETERS.values() if p == parameter)
        print(f"{parameter}: {np.isfinite(cube[0]).mean():.0%} of cells have data -> {', '.join(variables)}", flush=True)
        rows += grid_products(
            cube,
            dates,
            file_stem=f"power-{parameter}",
            variables=variables,
            units=units,
            source=f"NASA POWER {parameter} (MERRA-2)",
            version=version,
        )
    return rows


def publish(rows: list[dict]) -> None:
    index = storage() / "index.json"
    kept = []
    if index.exists():
        current = json.loads(index.read_text(encoding="utf-8"))
        published = {(row["variable_id"], row["season"]) for row in rows}
        for row in current.get("products", []):
            vmax = row.get("vmax")
            if not isinstance(vmax, (int, float)) or not np.isfinite(vmax) or vmax <= 0:
                continue  # an unusable row the API would skip anyway
            if (row.get("variable_id"), row.get("season")) in published:
                continue  # replaced by this run
            kept.append(row)
    body = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "products": kept + rows}
    tmp = index.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=1), encoding="utf-8")
    tmp.replace(index)
    print(f"Published {len(rows)} grid products ({len(kept)} other rows kept) to {index}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--params", nargs="*", help="POWER parameters (default: every one cases use)")
    parser.add_argument("--analyse-only", action="store_true", help="skip the download, use the cache")
    parser.add_argument("--workers", type=int, default=6, help="parallel requests to NASA POWER")
    args = parser.parse_args()

    parameters = args.params or sorted({parameter for parameter, _, _ in POWER_PARAMETERS.values()})
    last_year = datetime.now(UTC).year - 1
    storage().mkdir(parents=True, exist_ok=True)
    if not args.analyse_only:
        asyncio.run(download(parameters, last_year, args.workers))
    rows = analyse(parameters, last_year)
    if not rows:
        print("No grid was built; the index was not changed.")
        return 1
    publish(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
