"""Vertical profile of trends (PLAN_ANALYTICS section 8.6)."""

from __future__ import annotations

import pytest

from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_case
from earthtrend.analytics.spatial.profile import (
    PATTERN_T_PROFILE,
    climatological_tropopause_hpa,
    vertical_profile,
)

LEVELS = [1000.0, 850.0, 500.0, 300.0, 100.0, 50.0, 10.0]


def _profile(slopes: list[float], seed: int = 0) -> list:
    meta = default_meta(variable_id="T", region_id="globe", units="K")
    return [
        synthetic_case(meta, slope_per_decade=s, phi=0.3, sigma=0.3, seed=seed + k)[0]
        for k, s in enumerate(slopes)
    ]


def test_warming_below_cooling_above_sets_pattern() -> None:
    series = _profile([0.3, 0.3, 0.25, 0.1, -0.4, -0.6, -0.8])
    prof = vertical_profile(LEVELS, series, tropopause_hpa=200.0)
    assert PATTERN_T_PROFILE in prof.patterns
    assert [lv.level_hpa for lv in prof.levels] == sorted(LEVELS, reverse=True)
    assert prof.levels[0].significant and prof.levels[0].slope_per_decade > 0
    assert prof.levels[-1].significant and prof.levels[-1].slope_per_decade < 0
    assert prof.sign_change_hpa == 100.0
    assert [lv.above_tropopause for lv in prof.levels] == [False] * 4 + [True] * 3
    assert all(lv.q_value is not None for lv in prof.levels)


def test_no_trend_gives_no_pattern() -> None:
    prof = vertical_profile(LEVELS, _profile([0.0] * 7, seed=50), tropopause_hpa=200.0)
    assert prof.patterns == []
    assert sum(lv.significant for lv in prof.levels) <= 1


def test_input_order_does_not_matter_and_latitude_fallback() -> None:
    series = _profile([0.3, 0.3, 0.25, 0.1, -0.4, -0.6, -0.8])
    a = vertical_profile(LEVELS, series, lat=0.0)
    b = vertical_profile(LEVELS[::-1], series[::-1], lat=0.0)
    assert a.tropopause_hpa == 100.0 and a.tropopause_source == "latitude"
    assert [lv.slope_per_decade for lv in a.levels] == [lv.slope_per_decade for lv in b.levels]


def test_tropopause_fallback_bands() -> None:
    assert climatological_tropopause_hpa(10) == 100.0
    assert climatological_tropopause_hpa(-45) == 250.0
    assert climatological_tropopause_hpa(80) == 300.0


def test_validation_errors() -> None:
    series = _profile([0.0, 0.0])
    with pytest.raises(ValueError, match="one series per level"):
        vertical_profile([1000.0], series, lat=0)
    with pytest.raises(ValueError, match="tropopause_hpa or lat"):
        vertical_profile([1000.0, 500.0], series)
    with pytest.raises(ValueError, match="unique"):
        vertical_profile([500.0, 500.0], series, lat=0)
    other = synthetic_case(default_meta(variable_id="Q", region_id="globe"))[0]
    with pytest.raises(ValueError, match="share"):
        vertical_profile([1000.0, 500.0], [series[0], other], lat=0)
