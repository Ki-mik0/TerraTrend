from datetime import date

import numpy as np
import pytest

from earthtrend.analytics import regional_series
from earthtrend.analytics.regional.reduce import weighted_mean
from earthtrend.analytics.regional.weights import area_weights
from earthtrend.analytics.simulate.synthetic import default_meta

DATES = [date(2000, m, 1) for m in range(1, 13)]


def test_uniform_field_gives_its_value() -> None:
    lat, lon = np.array([-30.0, 0.0, 45.0]), np.array([0.0, 10.0])
    cube = np.full((12, 3, 2), 7.5)
    s = regional_series(cube, lat, lon, np.ones((3, 2), bool), DATES, default_meta())
    assert s.values == pytest.approx([7.5] * 12)
    assert s.coverage == [1.0] * 12
    assert s.stable_fraction == 1.0


def test_cos_lat_weighting() -> None:
    lat, lon = np.array([0.0, 60.0]), np.array([0.0])
    w = area_weights(lat, lon, np.ones((2, 1)))
    np.testing.assert_allclose(w[:, 0], [1.0, 0.5], atol=1e-12)
    cube = np.array([[[1.0], [3.0]]])
    mean, cov = weighted_mean(cube, w)
    assert mean[0] == pytest.approx((1 * 1 + 3 * 0.5) / 1.5)
    assert cov[0] == 1.0


def test_fractional_region_mask() -> None:
    w = area_weights(np.array([0.0]), np.array([0.0, 1.0]), np.array([[1.0, 0.25]]))
    mean, _ = weighted_mean(np.array([[[0.0, 10.0]]]), w)
    assert mean[0] == pytest.approx(10 * 0.25 / 1.25)


def test_month_with_low_coverage_is_a_gap() -> None:
    w = np.ones((1, 4))
    cube = np.ones((2, 1, 4))
    cube[1, 0, :2] = np.nan  # 50% coverage < 70%
    mean, cov = weighted_mean(cube, w)
    assert mean[0] == 1.0
    assert np.isnan(mean[1])
    assert cov[1] == 0.5


def test_unstable_cells_are_excluded_and_reported() -> None:
    lat, lon = np.array([0.0]), np.array([0.0, 1.0])
    cube = np.ones((12, 1, 2))
    cube[:, 0, 1] = 100.0
    cube[:6, 0, 1] = np.nan  # 50% valid -> not in the stable mask
    s = regional_series(cube, lat, lon, np.ones((1, 2), bool), DATES, default_meta())
    assert s.values == [1.0] * 12  # the flickering cell never enters the mean
    assert s.stable_fraction == pytest.approx(0.5)


def test_bad_inputs_raise() -> None:
    with pytest.raises(ValueError):
        area_weights(np.array([0.0]), np.array([0.0]), np.ones((2, 2)))
    with pytest.raises(ValueError):
        area_weights(np.array([0.0]), np.array([0.0]), np.array([[1.5]]))
    with pytest.raises(ValueError):
        regional_series(
            np.ones((12, 1, 1)),
            np.array([0.0]),
            np.array([0.0]),
            np.zeros((1, 1), bool),
            DATES,
            default_meta(),
        )
