"""Stage A4: non-linearity, change points, per-month trends, block bootstrap."""

import time
from datetime import date

import numpy as np
import pytest

from earthtrend.analytics import (
    AnalysisOptions,
    RegionalSeries,
    SensorEvent,
    TrendResult,
    analyze_series,
    build_protocol,
)
from earthtrend.analytics.simulate.synthetic import ar1_noise, default_meta, synthetic_case
from earthtrend.analytics.trend import changepoint as cpmod
from earthtrend.analytics.trend.bootstrap import block_bootstrap, block_length
from earthtrend.analytics.trend.nonlinear import fit_spline

N = 45 * 12
DATES = [date(1981 + i // 12, i % 12 + 1, 1) for i in range(N)]
T_DEC = np.arange(N) / 120  # decades since start


def _series(values: np.ndarray) -> RegionalSeries:
    return RegionalSeries(meta=default_meta(), dates=DATES, values=values.tolist())


def _noise(seed: int, sigma: float = 0.4) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, sigma, N)


# ---------------------------------------------------------------- non-linearity


def test_quadratic_trend_is_accelerating() -> None:
    r = analyze_series(_series(0.15 * T_DEC**2 + _noise(3)))
    assert r.nonlinear is not None
    assert r.nonlinear.shape == "accelerating"
    assert r.nonlinear.delta_aic >= 4
    d = r.nonlinear.derivative_per_decade
    assert d[-1] > d[0]


def test_cooling_that_speeds_up_is_accelerating_too() -> None:
    r = analyze_series(_series(-0.15 * T_DEC**2 + _noise(4)))
    assert r.nonlinear is not None and r.nonlinear.shape == "accelerating"


def test_saturating_trend_is_decelerating() -> None:
    r = analyze_series(_series(2.0 * (1 - np.exp(-T_DEC / 1.0)) + _noise(5)))
    assert r.nonlinear is not None and r.nonlinear.shape == "decelerating"


def test_linear_trend_stays_linear() -> None:
    s, _ = synthetic_case(n_years=45, slope_per_decade=0.7, phi=0.5, seed=1)
    r = analyze_series(s)
    assert r.nonlinear is not None and r.nonlinear.shape == "linear"
    nl = r.nonlinear
    assert len(nl.years) == len(nl.curve) == len(nl.curve_low) == len(nl.derivative_per_decade)
    assert all(
        lo <= c <= hi for lo, c, hi in zip(nl.curve_low, nl.curve, nl.curve_high, strict=True)
    )


def test_spline_needs_ten_years() -> None:
    assert fit_spline(np.arange(2000, 2008), np.arange(8.0)) is None


@pytest.mark.slow
def test_acceleration_false_alarm_rate() -> None:
    hits = 0
    for seed in range(100):
        s, _ = synthetic_case(n_years=40, slope_per_decade=0.5, phi=0.5, seed=seed)
        nl = analyze_series(s).nonlinear
        hits += nl is not None and nl.shape in ("accelerating", "decelerating")
    assert hits <= 7


# ---------------------------------------------------------------- change points


def test_step_is_found_at_the_right_month() -> None:
    step = np.where(np.arange(N) >= 252, 1.2, 0.0)  # Jan 2002
    r = analyze_series(_series(step + _noise(6)), AnalysisOptions(changepoints=True))
    assert len(r.changepoints) >= 1
    cp = r.changepoints[0]
    assert cp.method == "beast" and cp.probability is not None and cp.probability > 0.5
    assert abs((cp.at.year - 2002) * 12 + cp.at.month - 1) <= 3
    assert cp.jump == pytest.approx(1.2, abs=0.3)


def test_no_changepoints_on_plain_noise() -> None:
    r = analyze_series(_series(_noise(7)), AnalysisOptions(changepoints=True))
    assert r.changepoints == []


def test_changepoints_are_off_by_default_and_reproducible() -> None:
    s = _series(np.where(np.arange(N) >= 252, 1.2, 0.0) + _noise(6))
    assert analyze_series(s).changepoints == []
    a = analyze_series(s, AnalysisOptions(changepoints=True)).changepoints
    b = analyze_series(s, AnalysisOptions(changepoints=True)).changepoints
    assert a == b


def test_pelt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("Rbeast unavailable")

    monkeypatch.setattr(cpmod, "_beast", broken)
    step = np.where(np.arange(N) >= 252, 1.5, 0.0)
    r = analyze_series(_series(step + _noise(8, 0.3)), AnalysisOptions(changepoints=True))
    assert [c.method for c in r.changepoints] == ["pelt"]
    assert abs(r.changepoints[0].at.year - 2002) <= 1


def test_detected_changepoint_feeds_the_artifact_check() -> None:
    values = 0.07 * T_DEC * 10 / 10 + np.where(np.arange(N) >= 252, 1.0, 0.0) + _noise(9, 0.3)
    pr = build_protocol(
        _series(values),
        AnalysisOptions(changepoints=True),
        sensor_events=[SensorEvent(date=date(2002, 3, 1), code="new_sensor")],
    )
    assert "possible_artifact" in pr.caveats
    assert pr.verdict not in ("proven", "strong")


# ---------------------------------------------------------------- per-month trends


def test_monthly_trends_find_the_summer_signal() -> None:
    summer = np.isin(np.arange(N) % 12, [5, 6, 7])
    values = _noise(10, 0.5) + np.where(summer, 0.6 * T_DEC, 0.0)
    r = analyze_series(_series(values))
    sig = [m.month for m in r.seasonal_breakdown if m.significant]
    assert {6, 7, 8} <= set(sig)
    assert len(sig) <= 5
    jul = r.seasonal_breakdown[6]
    assert jul.month == 7 and jul.n_years == 45
    assert jul.slope_per_decade == pytest.approx(0.6, abs=0.2)
    assert all(m.q_value is None or m.q_value >= (m.p_mk or 0) for m in r.seasonal_breakdown)


def test_no_monthly_breakdown_for_seasonal_cases() -> None:
    s, _ = synthetic_case(n_years=30, slope_per_decade=0.5, seed=1)
    assert analyze_series(s, AnalysisOptions(season="JJA")).seasonal_breakdown == []


# ---------------------------------------------------------------- bootstrap


def test_block_length_rule() -> None:
    assert block_length(540, 0.0) == round(540 ** (1 / 3))
    assert block_length(540, 0.6) == round(540 ** (1 / 3) * 4)
    assert block_length(27, -0.5) == 3


def test_bootstrap_ci_is_wider_for_red_noise() -> None:
    t = 1981 + np.arange(N) / 12
    rng = np.random.default_rng(11)
    white = block_bootstrap(t, rng.normal(0, 1, N), seed=1)
    red = block_bootstrap(t, ar1_noise(N, 0.7, np.sqrt(1 - 0.49), rng), seed=1)
    assert white is not None and red is not None
    w = white.slope_ci95_per_decade[1] - white.slope_ci95_per_decade[0]
    r = red.slope_ci95_per_decade[1] - red.slope_ci95_per_decade[0]
    assert r > 1.5 * w
    assert red.block_length > white.block_length


def test_bootstrap_is_seeded_and_covers_the_truth() -> None:
    s, _ = synthetic_case(n_years=45, slope_per_decade=0.7, phi=0.5, seed=2)
    o = AnalysisOptions(bootstrap=True, n_boot=1000, seed=7)
    a, b = analyze_series(s, o), analyze_series(s, o)
    assert a.bootstrap == b.bootstrap and a.bootstrap is not None
    lo, hi = a.bootstrap.slope_ci95_per_decade
    assert lo < 0.7 < hi


# ---------------------------------------------------------------- budget and contract


def test_expert_case_within_budget() -> None:
    s, _ = synthetic_case(n_years=45, slope_per_decade=0.7, phi=0.5, seed=1)
    o = AnalysisOptions(changepoints=True, bootstrap=True)
    analyze_series(s, o)
    t0 = time.perf_counter()
    r = analyze_series(s, o)
    assert time.perf_counter() - t0 < 3.0  # section 14: case with bootstrap + BEAST
    assert TrendResult.model_validate_json(r.model_dump_json()) == r
