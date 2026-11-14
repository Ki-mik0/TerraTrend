"""Items of the main PLAN_ANALYTICS that close gaps in stages A1-A5."""

from datetime import date, timedelta

import numpy as np
import pytest

from earthtrend.analytics import (
    AnalysisOptions,
    RegionalSeries,
    SensorEvent,
    SplitResult,
    Zone,
    analyze_series,
    build_protocol,
    regional_series,
)
from earthtrend.analytics.preprocess.aggregate import daily_to_monthly
from earthtrend.analytics.simulate.surrogates import iaaft_surrogate, inject_signal
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_case, synthetic_series
from earthtrend.analytics.validation.giovanni import compare

# ---------------------------------------------------------------- 4.1 daily -> monthly


def test_daily_to_monthly_rules() -> None:
    days = [date(2000, 1, 1) + timedelta(days=i) for i in range(60)]  # Jan + Feb (leap)
    vals: list[float | None] = [1.0] * 31 + [2.0] * 29
    vals[31:40] = [None] * 9  # Feb: 20 of 29 days -> < 80%, invalid
    d, mean = daily_to_monthly(days, vals, "mean")
    assert d == [date(2000, 1, 1), date(2000, 2, 1)]
    assert mean == [1.0, None]
    vals2: list[float | None] = [1.0] * 60
    vals2[0:3] = [None] * 3  # Jan: 28 of 31 days -> valid; sum scaled to the full month
    _, total = daily_to_monthly(days, vals2, "sum")
    assert total[0] == pytest.approx(31.0)
    _, mx = daily_to_monthly(days, [float(i) for i in range(60)], "max")
    assert mx == [30.0, 59.0]
    with pytest.raises(ValueError):
        daily_to_monthly(days, vals2, "median")


def test_daily_series_is_analysed_as_monthly() -> None:
    rng = np.random.default_rng(0)
    start = date(1985, 1, 1)
    n = (date(2020, 12, 31) - start).days + 1
    days = [start + timedelta(days=i) for i in range(n)]
    t = np.arange(n) / 3652.5
    x = 0.5 * t + rng.normal(0, 2.0, n)
    meta = default_meta(frequency="daily", aggregation="mean")
    r = analyze_series(RegionalSeries(meta=meta, dates=days, values=x.tolist()))
    assert r.n_used == 36 * 12
    assert r.verdict.code == "strong"
    assert r.primary_slope_per_decade == pytest.approx(0.5, abs=0.15)


# ---------------------------------------------------------------- expert mode, facts


def test_expert_mode_adds_stl_glsar_bootstrap() -> None:
    s, _ = synthetic_case(n_years=30, seasonal_amplitude=8, slope_per_decade=0.6, phi=0.5, seed=1)
    plain = analyze_series(s)
    assert plain.stl is None and plain.bootstrap is None and plain.test("glsar") is None
    r = analyze_series(s, AnalysisOptions(expert=True, n_boot=500))
    assert r.stl is not None and len(r.stl.trend) == 360
    seasonal = np.array([v for v in r.stl.seasonal if v is not None])
    assert seasonal.max() - seasonal.min() > 10  # recovers the cycle (amplitude 8)
    g = r.test("glsar")
    assert g is not None and g.slope_per_decade == pytest.approx(0.6, abs=0.2)
    assert r.bootstrap is not None


def test_summary_text_facts_hold_only_result_numbers() -> None:
    s, _ = synthetic_case(n_years=40, slope_per_decade=0.7, phi=0.5, seed=1)
    r = analyze_series(s)
    f = r.summary_text_facts
    assert f["verdict"] == r.verdict.code
    assert f["slope_per_decade"] == pytest.approx(r.primary_slope_per_decade, abs=1e-3)
    assert f["p_mk_ar1"] == pytest.approx(r.test("mk_ar1").p_value, abs=1e-4)  # type: ignore[union-attr]
    assert f["period_start"] == "1981-01-01"
    assert r.ai_opinion is None  # M1 arrives in stage A6


# ---------------------------------------------------------------- 4.2 sensor events, 17 zones


def test_sensor_event_flag_triggers_changepoint_check() -> None:
    rng = np.random.default_rng(3)
    n = 40 * 12
    dates = [date(1981 + i // 12, i % 12 + 1, 1) for i in range(n)]
    x = rng.normal(0, 0.3, n) + np.where(np.arange(n) >= 252, 1.0, 0.0)
    s = RegionalSeries(meta=default_meta(), dates=dates, values=x.tolist())
    ev = [SensorEvent(date=date(2002, 2, 1), code="new_sensor")]
    pr = build_protocol(s, sensor_events=ev)  # change points NOT requested
    q = pr.item("quality")
    assert q is not None
    codes = {f["code"] for f in q.details["flags"]}
    assert "sensor_event_in_period" in codes
    assert "possible_artifact" in pr.caveats
    assert q.details["changepoints"]


def test_split_and_zones_travel_in_details() -> None:
    s, _ = synthetic_case(n_years=40, slope_per_decade=0.7, phi=0.5, seed=1)
    split = SplitResult(sig_pos=0.5, sig_neg=0.0, nonsig=0.5, split_flag=False)
    zone = Zone(
        id=1,
        sign=1,
        n_cells=10,
        area_km2=1e5,
        area_share=0.5,
        mean_slope_per_decade=0.7,
        centroid=(10.0, 20.0),
        bbox=(5.0, 15.0, 15.0, 25.0),
    )
    q = build_protocol(s, split=split, zones=[zone]).item("quality")
    assert q is not None
    assert q.details["split"]["sig_pos"] == 0.5
    assert q.details["zones"][0]["id"] == 1


# ---------------------------------------------------------------- 12 generator API


def test_synthetic_series_plan_signature() -> None:
    s = synthetic_series(n_years=40, trend_per_decade=0.5, noise_sd=0.5, ar1=0.3, seed=1)
    v = np.array(s.values, dtype=float)
    assert v.size == 480
    r = analyze_series(s)
    assert r.primary_slope_per_decade == pytest.approx(0.5, abs=0.15)
    t = synthetic_series(n_years=30, trend_per_decade=0, season_amp=0, noise="student_t", seed=2)
    assert np.nanstd(np.array(t.values, dtype=float)) == pytest.approx(0.5, abs=0.1)
    st = synthetic_series(
        n_years=30, trend_per_decade=0, season_amp=0, noise_sd=0.1, step=(2000, 2.0), seed=3
    )
    sv = np.array(st.values, dtype=float)
    assert sv[(2000 - 1981) * 12 :].mean() - sv[: (2000 - 1981) * 12].mean() == pytest.approx(
        2.0, abs=0.1
    )
    g = synthetic_series(gaps=0.2, seed=4)
    assert 0.1 < np.mean([x is None for x in g.values]) < 0.3
    with pytest.raises(ValueError):
        synthetic_series(noise="cauchy")


def test_iaaft_surrogate_is_seeded() -> None:
    x = np.random.default_rng(0).normal(size=240)
    np.testing.assert_array_equal(iaaft_surrogate(x, seed=1), iaaft_surrogate(x, seed=1))
    assert not np.array_equal(iaaft_surrogate(x, seed=1), iaaft_surrogate(x, seed=2))


@pytest.mark.parametrize("kind", ["none", "linear", "step", "accel", "trend_plus_step"])
def test_inject_signal_labels(kind: str) -> None:
    x = np.random.default_rng(5).normal(0, 1, 480)
    y, lab = inject_signal(x, kind, snr=0.5, when=0.5, seed=1)  # type: ignore[arg-type]
    assert lab.kind == kind and y.shape == x.shape
    if kind in ("linear", "trend_plus_step"):
        assert abs(lab.slope_per_decade) == pytest.approx(0.5 * np.std(x))
    if kind in ("step", "trend_plus_step"):
        assert lab.step_index == 240 and abs(lab.step_size) == pytest.approx(0.5 * np.std(x))
    if kind == "none":
        np.testing.assert_array_equal(y, x)


# ---------------------------------------------------------------- 13.4 Giovanni


def test_stable_mask_switch_for_giovanni_comparison() -> None:
    lat, lon = np.array([0.0]), np.array([0.0, 1.0])
    cube = np.ones((12, 1, 2))
    cube[:, 0, 1] = 3.0
    cube[:6, 0, 1] = np.nan  # flickering cell
    dates = [date(2000, m, 1) for m in range(1, 13)]
    masked = regional_series(cube, lat, lon, np.ones((1, 2), bool), dates, default_meta())
    raw = regional_series(
        cube, lat, lon, np.ones((1, 2), bool), dates, default_meta(), use_stable_mask=False
    )
    assert masked.values[-1] == pytest.approx(1.0)
    assert raw.values[-1] == pytest.approx(2.0)  # Giovanni-style: both cells when present


def test_giovanni_agreement_needs_two_percent_rule() -> None:
    dates = [date(2000 + i // 12, i % 12 + 1, 1) for i in range(48)]
    base = [float(np.sin(i / 2)) * 10 for i in range(48)]
    close = (dates, [v + 0.1 for v in base])  # MAD 0.1 vs range ~20 -> 0.5%
    far = (dates, [v * 1.0 + 1.0 for v in base])  # MAD 1.0 -> ~5% of range
    assert compare(close, (dates, base)).passes()  # type: ignore[arg-type]
    agr = compare(far, (dates, base))  # type: ignore[arg-type]
    assert agr.correlation > 0.99 and not agr.passes()
