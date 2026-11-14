"""Grid trends must agree cell by cell with the series core."""

import time

import numpy as np
import pytest

from earthtrend.analytics import analyze_grid
from earthtrend.analytics.preprocess.aggregate import annual_means, decimal_year, split_dates
from earthtrend.analytics.preprocess.anomalies import anomalies
from earthtrend.analytics.preprocess.climatology import monthly_climatology
from earthtrend.analytics.simulate.synthetic import generate_grid
from earthtrend.analytics.spatial.grid_trend import grid_trends
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.ols import ols_ar1
from earthtrend.analytics.trend.sen import sen_slope


@pytest.fixture(scope="module")
def small_grid() -> tuple[list, np.ndarray, np.ndarray]:
    slope = np.linspace(-1.0, 1.0, 12).reshape(3, 4)
    dates, cube = generate_grid(
        slope_field=slope, n_years=30, seasonal_amplitude=5.0, phi=0.5, seed=3
    )
    cube[5:40, 0, 0] = np.nan  # some monthly gaps (< 20%) in one cell
    return dates, cube, slope


def test_cells_match_series_core(small_grid: tuple) -> None:
    dates, cube, _ = small_grid
    f = grid_trends(cube, dates)
    years, months = split_dates(dates)
    t = decimal_year(years, months)
    for i in range(cube.shape[1]):
        for j in range(cube.shape[2]):
            y = cube[:, i, j]
            mean, _ = monthly_climatology(y, years, months)
            anom = anomalies(y, months, mean)
            ols = ols_ar1(t, anom)
            assert ols is not None
            assert f.slope_ols[i, j] == pytest.approx(ols.slope * 10, rel=1e-9)
            assert f.p_ols[i, j] == pytest.approx(ols.p_value, rel=1e-6, abs=1e-12)
            assert f.n_eff[i, j] == pytest.approx(ols.n_eff, rel=1e-9)

            ay, av = annual_means(anom, years, months)
            mk = mk_ar1(av)
            assert mk is not None
            sen = sen_slope(ay.astype(float), av, mk.var_s)
            assert sen is not None
            assert f.slope[i, j] == pytest.approx(sen.slope * 10, rel=1e-9)
            if np.isnan(av).any():
                # Missing years: the grid's rank autocorrelation uses consecutive existing
                # years only, the series core compresses gaps (documented difference).
                continue
            assert f.p_mk[i, j] == pytest.approx(mk.p_value, rel=1e-6, abs=1e-12)
            assert f.ci_low[i, j] == pytest.approx(sen.ci95[0] * 10, rel=1e-9)
            assert f.ci_high[i, j] == pytest.approx(sen.ci95[1] * 10, rel=1e-9)


def test_recovers_slope_field(small_grid: tuple) -> None:
    dates, cube, slope = small_grid
    f = grid_trends(cube, dates)
    assert np.corrcoef(f.slope.ravel(), slope.ravel())[0, 1] > 0.9


def test_gappy_cells_and_mask_are_nan() -> None:
    dates, cube = generate_grid(slope_field=np.zeros((2, 2)), n_years=20, seed=1)
    cube[: len(dates) // 4, 0, 0] = np.nan  # 25% gaps > 20%
    mask = np.array([[True, True], [True, False]])
    f = grid_trends(cube, dates, cell_mask=mask)
    assert f.valid.tolist() == [[False, True], [True, False]]
    assert np.isnan(f.slope[0, 0]) and np.isnan(f.slope[1, 1])


def test_baseline_barely_changes_slopes(small_grid: tuple) -> None:
    # A different baseline shifts each calendar month by its own constant, which nudges
    # the OLS slope slightly; it must not change it materially.
    dates, cube, _ = small_grid
    a = grid_trends(cube, dates)
    b = grid_trends(cube, dates, baseline=(1991, 2000))
    np.testing.assert_allclose(a.slope_ols, b.slope_ols, atol=0.02)


def test_region_mask_restricts_fdr_and_summary() -> None:
    lat, lon = np.array([0.0, 1.0]), np.array([0.0, 1.0, 2.0])
    dates, cube = generate_grid(slope_field=np.full((2, 3), 1.0), n_years=30, seed=2)
    region = np.array([[1.0, 1.0, 0.0], [0.5, 0.0, 0.0]])
    prod = analyze_grid(cube, lat, lon, dates, region_mask=region)
    assert prod.summary.n_cells_valid == 3
    assert not prod.sig_fdr[:, 2].any()


@pytest.mark.slow
def test_one_degree_global_grid_under_five_seconds() -> None:
    lat, lon = np.arange(-89.5, 90, 1.0), np.arange(-179.5, 180, 1.0)
    dates, cube = generate_grid(slope_field=np.zeros((lat.size, lon.size)), n_years=45, seed=0)
    analyze_grid(cube[:, :2, :2], lat[:2], lon[:2], dates)  # compile / load numba cache
    t0 = time.perf_counter()
    analyze_grid(cube, lat, lon, dates)
    assert time.perf_counter() - t0 < 5.0
