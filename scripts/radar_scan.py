"""Build the radar from real NASA POWER data and publish it where the API reads it.

    python scripts/radar_scan.py            # all POWER variables x all catalog regions
    python scripts/radar_scan.py --dry-run  # scan, print the summary, write nothing

For every catalog region and every variable NASA POWER covers (one variable per POWER parameter, so
the same series is not scanned twice) the monthly regional series is downloaded, the analytics radar
scan runs over all of them at once (FDR across the whole set), and the result is written to
`STORAGE_ROOT/radar/<version>.json` with `latest.json` pointing at it. The running API picks the new
version up without a restart. Without these files the API serves its built-in seed radar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earthtrend.api.domain.cases.model import CaseSpec  # noqa: E402
from earthtrend.api.infrastructure.cases.sources import POWER_PARAMETERS, PowerSeriesSource  # noqa: E402
from earthtrend.api.infrastructure.catalog.memory import seed_catalog  # noqa: E402
from earthtrend.api.infrastructure.radar.memory import seed_radar  # noqa: E402

FIRST_YEAR = 1991  # thirty full years and more: enough for a stable trend, quick to download


def _variables() -> dict[str, str]:
    """One catalog variable per POWER parameter."""
    chosen: dict[str, str] = {}
    for variable_id, (parameter, _, _) in POWER_PARAMETERS.items():
        chosen.setdefault(parameter, variable_id)
    return {variable_id: parameter for parameter, variable_id in chosen.items()}


async def _collect(last_year: int) -> list[dict]:
    catalog = seed_catalog()
    regions = await catalog.list_regions()
    power = PowerSeriesSource(timeout=60.0)
    gate = asyncio.Semaphore(4)  # be gentle with the free API
    rows: list[dict] = []

    async def one(variable_id: str, region) -> None:
        spec = CaseSpec(variable_id, region.id, f"{FIRST_YEAR}-01", f"{last_year}-12")
        async with gate:
            series = await power.fetch(spec, tuple(region.bbox), getattr(region, "area_km2", None))
        if series is None:
            print(f"  skip {variable_id} x {region.id}: POWER returned no usable series", flush=True)
            return
        rows.append({"series": series, "region_group": getattr(region, "group", None) or region.id.split("_")[0]})
        print(f"  ok   {variable_id} x {region.id}", flush=True)

    await asyncio.gather(*(one(variable_id, region) for variable_id in _variables() for region in regions))
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="scan and print, write nothing")
    args = parser.parse_args()

    last_year = datetime.now(UTC).year - 1
    print(f"Downloading NASA POWER series {FIRST_YEAR}-{last_year} ...", flush=True)
    rows = await _collect(last_year)
    if not rows:
        print("No series downloaded; the radar was not changed.")
        return 1

    radar = seed_radar()
    summary = await radar.scan(rows)
    product = radar._overlay  # the scan result the service would serve
    assert product is not None
    version = f"power-{datetime.now(UTC):%Y-%m-%d}"
    body = {
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": f"NASA POWER monthly, {FIRST_YEAR}-{last_year}, {len(rows)} series",
        "items": [asdict(item) for item in product.items],
        "clusters": [{**asdict(cluster), "region_ids": list(cluster.region_ids)} for cluster in product.clusters],
    }
    print(f"Scanned {summary['entries']} series, {summary['cards']} radar cards, {len(body['clusters'])} clusters.")
    if args.dry_run:
        return 0
    folder = Path(os.environ.get("STORAGE_ROOT", ROOT / "data" / "storage")) / "radar"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{version}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "latest.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    print(f"Published radar {version} to {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
