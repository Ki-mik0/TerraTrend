"""Real data: Giovanni area-averaged MERRA-2 M2TMNXSLV T2M over the Arctic.

Fixture: export from https://giovanni.gsfc.nasa.gov/ -> "Time Series, Area-Averaged",
variable M2TMNXSLV T2M, bbox -180,66.5,180,90, 1980-01..2024-12, CSV download, saved as
tests/analytics/fixtures/giovanni_m2tmnxslv_t2m_arctic.csv. Skipped until it exists.
"""

import time
from pathlib import Path

import pytest

from earthtrend.analytics import RegionalSeries, SeriesMeta, analyze_series
from earthtrend.analytics.validation.giovanni import load_giovanni_csv

FIXTURE = Path(__file__).parents[1] / "fixtures" / "giovanni_m2tmnxslv_t2m_arctic.csv"


@pytest.mark.skipif(not FIXTURE.exists(), reason="Giovanni CSV fixture not exported yet")
def test_arctic_warming_is_strong() -> None:
    dates, values = load_giovanni_csv(FIXTURE)
    assert len(dates) >= 12 * 40
    meta = SeriesMeta(
        variable_id="t2m",
        concept_id="air_temperature_2m",
        dataset_id="M2TMNXSLV",
        dataset_version="5.12.4",
        units="K",
        region_id="arctic",
    )
    series = RegionalSeries(meta=meta, dates=dates, values=values)
    t0 = time.perf_counter()
    r = analyze_series(series)
    elapsed = time.perf_counter() - t0
    assert r.verdict.code == "strong"
    assert r.direction == "increasing"
    assert r.primary_ci95 is not None and r.primary_ci95[0] > 0
    assert elapsed < 0.3
