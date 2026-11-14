"""Performance targets of PLAN_ANALYTICS section 14 (pytest-benchmark).

Each benchmark asserts its target on the median; ``--benchmark-compare-fail=median:20%``
against a saved baseline blocks a > 20% regression (``make bench``).
"""

import numpy as np
import pytest

from earthtrend.analytics import AnalysisOptions, analyze_grid, build_protocol
from earthtrend.analytics.evidence.triangle import trend_triangle
from earthtrend.analytics.simulate.synthetic import default_meta, generate_grid, synthetic_case

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module")
def case():  # type: ignore[no-untyped-def]
    s, _ = synthetic_case(
        n_years=45, base=260, seasonal_amplitude=15, slope_per_decade=0.7, phi=0.5, seed=1
    )
    w, _ = synthetic_case(
        meta=default_meta(dataset_id="w"),
        n_years=45,
        base=260,
        seasonal_amplitude=15,
        slope_per_decade=0.7,
        phi=0.5,
        seed=2,
    )
    return s, w


def test_full_case_under_300ms(benchmark, case) -> None:  # type: ignore[no-untyped-def]
    s, w = case
    benchmark.pedantic(
        build_protocol, args=(s,), kwargs={"witnesses": [w]}, rounds=5, warmup_rounds=1
    )
    assert benchmark.stats.stats.median < 0.3


def test_case_with_bootstrap_and_beast_under_3s(benchmark, case) -> None:  # type: ignore[no-untyped-def]
    s, _ = case
    opts = AnalysisOptions(changepoints=True, bootstrap=True)
    benchmark.pedantic(build_protocol, args=(s, opts), rounds=3, warmup_rounds=1)
    assert benchmark.stats.stats.median < 3.0


def test_triangle_40_years_under_100ms(benchmark) -> None:  # type: ignore[no-untyped-def]
    years = np.arange(1981, 2021)
    a = 0.03 * (years - 1981) + np.random.default_rng(0).normal(0, 0.2, years.size)
    benchmark.pedantic(trend_triangle, args=(years, a, 1), rounds=10, warmup_rounds=1)
    assert benchmark.stats.stats.median < 0.1


@pytest.mark.slow
def test_grid_one_degree_under_5s(benchmark) -> None:  # type: ignore[no-untyped-def]
    lat, lon = np.arange(-89.5, 90, 1.0), np.arange(-179.5, 180, 1.0)
    dates, cube = generate_grid(slope_field=np.zeros((lat.size, lon.size)), n_years=45, seed=0)
    analyze_grid(cube[:, :2, :2], lat[:2], lon[:2], dates)  # compile / load numba cache
    benchmark.pedantic(analyze_grid, args=(cube, lat, lon, dates), rounds=2)
    assert benchmark.stats.stats.median < 5.0
