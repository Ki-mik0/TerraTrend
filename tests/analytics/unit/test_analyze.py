import math
import time
from datetime import date

import numpy as np
import pytest

from earthtrend.analytics import AnalysisOptions, RegionalSeries, TrendResult, analyze_series
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_case


def _warming(**kw: object) -> RegionalSeries:
    params: dict[str, object] = dict(
        n_years=45,
        base=260.0,
        seasonal_amplitude=15.0,
        slope_per_decade=0.7,
        phi=0.5,
        sigma=1.0,
        seed=1,
    )
    params.update(kw)
    return synthetic_case(**params)[0]


def test_clear_warming_is_strong_and_increasing() -> None:
    r = analyze_series(_warming())
    assert r.verdict.code == "strong"
    assert r.verdict.direction == r.direction == "increasing"
    assert r.verdict.ruleset == "verdict_rules_v0"
    assert {t.method for t in r.tests} == {"ols_ar1", "ols_ar1_annual", "mk_ar1", "sen"}
    assert r.primary_ci95 is not None and r.primary_ci95[0] > 0
    assert r.years_to_detect is not None and r.years_to_detect < 45
    assert r.years_to_detect_remaining == 0.0
    assert r.n_used == 540 and r.years_of_data == 45


def test_cooling_is_decreasing() -> None:
    r = analyze_series(_warming(slope_per_decade=-0.7))
    assert r.verdict.code == "strong" and r.direction == "decreasing"


def test_white_noise_is_no_evidence() -> None:
    s, _ = synthetic_case(n_years=40, slope_per_decade=0.0, seed=7)
    r = analyze_series(s)
    assert r.verdict.code == "no_evidence"
    assert r.direction == "none"


def test_constant_and_short_series_are_inadmissible() -> None:
    dates = [date(2000 + i // 12, i % 12 + 1, 1) for i in range(240)]
    const = RegionalSeries(meta=default_meta(), dates=dates, values=[5.0] * 240)
    r = analyze_series(const)
    assert r.verdict.code == "inadmissible" and r.tests == []

    short, _ = synthetic_case(n_years=8, slope_per_decade=5.0, seed=1)
    r = analyze_series(short)
    assert r.verdict.code == "inadmissible"
    assert "short_record" in {f.code for f in r.flags}
    assert r.tests  # tests still run, for transparency


def test_payload_is_aligned_for_the_chart() -> None:
    r = analyze_series(_warming())
    p = r.series_out
    n = len(p.dates)
    assert n == len(p.values) == len(p.anomalies) == len(p.trend) == len(p.ci_low) == len(p.ci_high)
    assert all(lo <= tr <= hi for lo, tr, hi in zip(p.ci_low, p.trend, p.ci_high, strict=True))
    assert p.values[0] is not None and p.values[0] > 200  # original units, not anomalies


def test_seasonal_analysis_uses_one_value_per_year() -> None:
    r = analyze_series(_warming(), AnalysisOptions(season="JJA"))
    assert r.n_used == 45
    assert all(d.month == 7 for d in r.series_out.dates)
    assert r.verdict.code == "strong"


def test_period_filter() -> None:
    r = analyze_series(_warming(), AnalysisOptions(period=(1990, 2009)))
    assert r.period_used == (date(1990, 1, 1), date(2009, 12, 1))
    assert r.years_of_data == 20


def test_log_transform_reports_percent_per_decade() -> None:
    dates = [date(2000 + i // 12, i % 12 + 1, 1) for i in range(360)]
    rng = np.random.default_rng(0)
    t = np.arange(360) / 12
    values = 5.0 * np.exp(0.02 * t + rng.normal(0, 0.05, 360))
    s = RegionalSeries(meta=default_meta(transform="log"), dates=dates, values=values.tolist())
    r = analyze_series(s)
    assert r.magnitude is not None and r.magnitude.percent_per_decade is not None
    assert r.magnitude.percent_per_decade == pytest.approx((math.exp(0.2) - 1) * 100, rel=0.05)


def test_quality_caveats_reach_the_verdict() -> None:
    s, _ = synthetic_case(n_years=40, slope_per_decade=1.0, gap_fraction=0.3, seed=2)
    s = s.model_copy(update={"stable_fraction": 0.3})
    r = analyze_series(s)
    assert {"many_gaps", "low_stable_coverage"} <= set(r.verdict.caveats)


def test_strength_never_exceeds_slice_maximum() -> None:
    assert analyze_series(_warming()).verdict.strength <= 45


def test_result_schema_builds_and_round_trips() -> None:
    schema = TrendResult.model_json_schema()
    assert "verdict" in schema["properties"]
    r = analyze_series(_warming())
    assert TrendResult.model_validate_json(r.model_dump_json()) == r


def test_series_validation() -> None:
    with pytest.raises(ValueError):
        RegionalSeries(meta=default_meta(), dates=[date(2000, 1, 1)], values=[1.0, 2.0])
    with pytest.raises(ValueError):
        RegionalSeries(
            meta=default_meta(), dates=[date(2000, 2, 1), date(2000, 1, 1)], values=[1.0, 2.0]
        )


def test_45_year_series_is_fast() -> None:
    s = _warming()
    analyze_series(s)  # warm-up
    t0 = time.perf_counter()
    analyze_series(s)
    assert time.perf_counter() - t0 < 0.3
