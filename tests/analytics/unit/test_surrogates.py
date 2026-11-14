from datetime import date

import numpy as np
import pytest

from earthtrend.analytics.simulate.surrogates import (
    apply_gaps,
    deseasonalize,
    iaaft,
    iaaft_window,
    insert_step,
    insert_trend,
    skewed_ar1,
    with_witness,
)
from earthtrend.analytics.simulate.synthetic import ar1_noise
from earthtrend.analytics.trend.power import years_to_detect
from earthtrend.analytics.validation.giovanni import compare
from earthtrend.analytics.validation.monte_carlo import (
    Scenario,
    make_case,
    method_rates,
    weatherhead_slope,
)


def _acf1(x: np.ndarray) -> float:
    x = x - x.mean()
    return float(x[:-1] @ x[1:] / (x @ x))


def test_iaaft_keeps_distribution_and_autocorrelation() -> None:
    rng = np.random.default_rng(0)
    x = np.exp(ar1_noise(1024, 0.7, 0.5, rng))  # skewed, autocorrelated
    s = iaaft(x, rng)
    xd = x - np.polyval(np.polyfit(np.arange(x.size), x, 1), np.arange(x.size))
    np.testing.assert_allclose(np.sort(s), np.sort(xd))  # identical values
    assert _acf1(s) == pytest.approx(_acf1(xd), abs=0.05)
    assert abs(np.corrcoef(s, x)[0, 1]) < 0.3  # a different realization


def test_iaaft_keeps_gaps_and_window_length() -> None:
    rng = np.random.default_rng(1)
    x = ar1_noise(480, 0.5, 1.0, rng)
    x[[3, 100, 400]] = np.nan
    assert np.isnan(iaaft(x, rng)[[3, 100, 400]]).all()
    assert iaaft_window(ar1_noise(960, 0.5, 1.0, rng), 480, rng).size == 480
    with pytest.raises(ValueError):
        iaaft_window(x, 300, rng)


def test_deseasonalize_and_inserts() -> None:
    x = np.tile(np.arange(12.0), 10)
    anom, cycle = deseasonalize(x)
    np.testing.assert_allclose(anom, 0.0)
    assert cycle[:12].tolist() == list(range(12))
    tr = insert_trend(np.zeros(120), 1.0)
    assert tr[-1] == pytest.approx(119 / 12 / 10)
    assert insert_step(np.zeros(5), 2, 3.0).tolist() == [0, 0, 3, 3, 3]
    assert np.isnan(apply_gaps(np.zeros(3), np.array([False, True, False]))[1])


def test_skewed_and_witness_generators() -> None:
    rng = np.random.default_rng(2)
    g = skewed_ar1(5000, 0.5, rng)
    assert (g > 0).all() and np.mean(g) > np.median(g)  # right-skewed
    assert _acf1(g) == pytest.approx(0.5, abs=0.07)
    a, b = with_witness(5000, 0.3, rng, shared=0.8)
    assert np.corrcoef(a, b)[0, 1] == pytest.approx(0.8, abs=0.05)


def test_make_case_kinds() -> None:
    for kind in ("ar1", "skewed", "iaaft", "witness"):
        s, w = make_case(Scenario(kind, kind, 0.5, n_years=20), seed=1)  # type: ignore[arg-type]
        assert len(s.values) == 240
        assert (len(w) == 1) == (kind == "witness")
    assert make_case(Scenario("s", "skewed"), 1)[0].meta.distribution == "skewed"


def test_weatherhead_slope_inverts_the_formula() -> None:
    phi = 0.5
    slope = weatherhead_slope(40, phi)
    sigma_n = 1 / np.sqrt(1 - phi**2)
    assert years_to_detect(slope, sigma_n, phi) == pytest.approx(40.0, rel=1e-9)


def test_method_rates_smoke() -> None:
    r = method_rates(Scenario("ar1", "ar1", 0.5, n_years=20), runs=30)
    assert set(r) == {"decision", "ols", "ols_annual", "mk", "sen_cover", "ols_cover"}
    assert all(0 <= v <= 1 for v in r.values())


def test_giovanni_compare() -> None:
    dates = [date(2000, m, 1) for m in range(1, 13)]
    a = (dates, [float(m) for m in range(12)])
    b = (dates, [float(m) + 0.1 for m in range(12)])
    agr = compare(a, b)
    assert agr.n_common == 12 and agr.correlation == pytest.approx(1.0)
    assert agr.bias == pytest.approx(-0.1) and agr.mean_abs_diff == pytest.approx(0.1)
    assert not agr.passes()  # fewer than 24 common months
