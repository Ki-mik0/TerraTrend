import numpy as np
import pytest

from earthtrend.analytics.simulate.synthetic import ar1_noise
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.ols import lag1_autocorrelation, ols_ar1
from earthtrend.analytics.trend.power import years_to_detect
from earthtrend.analytics.trend.sen import sen_slope

T = 2000 + (np.arange(240) + 0.5) / 12


def test_ols_on_an_exact_line() -> None:
    fit = ols_ar1(T, 3.0 + 0.2 * (T - 2000))
    assert fit is not None
    assert fit.slope == pytest.approx(0.2)
    assert fit.p_value < 1e-10


def test_ols_ignores_gaps_and_needs_three_points() -> None:
    y = 0.1 * (T - 2000)
    y[::3] = np.nan
    fit = ols_ar1(T, y)
    assert fit is not None and fit.slope == pytest.approx(0.1)
    assert ols_ar1(T[:2], y[:2]) is None


def test_n_eff_shrinks_with_autocorrelation() -> None:
    rng = np.random.default_rng(1)
    white = ols_ar1(T, rng.normal(size=T.size))
    red = ols_ar1(T, ar1_noise(T.size, 0.7, 1.0, rng))
    assert white is not None and red is not None
    assert red.n_eff < 0.4 * red.n
    assert white.n_eff > 0.7 * white.n
    assert red.p_value >= red.p_value_naive


def test_lag1_autocorrelation_estimates_phi() -> None:
    e = ar1_noise(20_000, 0.6, 1.0, np.random.default_rng(2))
    assert lag1_autocorrelation(e) == pytest.approx(0.6, abs=0.03)


def test_sen_on_exact_line_with_outlier() -> None:
    y = 0.5 * (T - 2000)
    y[100] = 1e6  # Sen is robust
    mk = mk_ar1(y)
    assert mk is not None
    sen = sen_slope(T, y, mk.var_s)
    assert sen is not None
    assert sen.slope == pytest.approx(0.5)
    assert sen.ci95[0] <= 0.5 <= sen.ci95[1]


def test_mk_detects_monotonic_series_and_rejects_constant() -> None:
    mk = mk_ar1(np.arange(50.0))
    assert mk is not None
    assert mk.z > 0 and mk.p_value < 1e-6 and mk.tau == pytest.approx(1.0)
    assert mk_ar1(np.ones(50)) is None
    assert mk_ar1(np.array([1.0, 2.0, np.nan])) is None


def test_mk_correction_is_never_below_one() -> None:
    rng = np.random.default_rng(3)
    alternating = np.tile([1.0, -1.0], 60) + rng.normal(0, 0.1, 120)  # negative lag-1
    mk = mk_ar1(alternating)
    assert mk is not None and mk.correction == 1.0


def test_years_to_detect_formula() -> None:
    assert years_to_detect(0.1, 1.0, 0.0) == pytest.approx(33.0 ** (2 / 3))
    assert years_to_detect(0.1, 1.0, 0.5) > years_to_detect(0.1, 1.0, 0.0)  # type: ignore[operator]
    assert years_to_detect(0.0, 1.0, 0.0) is None
