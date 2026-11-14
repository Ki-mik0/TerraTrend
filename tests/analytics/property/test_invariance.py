"""Properties every trend estimator must satisfy, whatever the series."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from earthtrend.analytics import RegionalSeries, TrendResult, analyze_series
from earthtrend.analytics.simulate.synthetic import synthetic_case

series_params = st.fixed_dictionaries(
    {
        "n_years": st.integers(12, 30),
        "slope_per_decade": st.floats(-2.0, 2.0),
        "phi": st.floats(0.0, 0.8),
        "seed": st.integers(0, 10_000),
    }
)


def _slopes(r: TrendResult) -> tuple[float, float]:
    ols = r.test("ols_ar1")
    assert ols is not None and ols.slope_per_decade is not None
    assert r.primary_slope_per_decade is not None
    return r.primary_slope_per_decade, ols.slope_per_decade


def _map(s: RegionalSeries, f) -> RegionalSeries:  # type: ignore[no-untyped-def]
    return s.model_copy(update={"values": [None if v is None else f(v) for v in s.values]})


@settings(max_examples=25, deadline=None)
@given(series_params, st.floats(-500.0, 500.0))
def test_adding_a_constant_keeps_slopes(params: dict, c: float) -> None:  # type: ignore[type-arg]
    s, _ = synthetic_case(**params)
    a = _slopes(analyze_series(s))
    b = _slopes(analyze_series(_map(s, lambda v: v + c)))
    assert b == pytest.approx(a, abs=1e-6)


@settings(max_examples=25, deadline=None)
@given(series_params, st.floats(0.01, 100.0))
def test_scaling_scales_slopes(params: dict, k: float) -> None:  # type: ignore[type-arg]
    s, _ = synthetic_case(**params)
    a = _slopes(analyze_series(s))
    b = _slopes(analyze_series(_map(s, lambda v: v * k)))
    assert b == pytest.approx((a[0] * k, a[1] * k), rel=1e-6, abs=1e-9)


@settings(max_examples=25, deadline=None)
@given(series_params)
def test_reversing_time_flips_the_sign(params: dict) -> None:  # type: ignore[type-arg]
    s, _ = synthetic_case(**params)
    rev = s.model_copy(update={"values": list(reversed(s.values))})
    a = _slopes(analyze_series(s))
    b = _slopes(analyze_series(rev))
    # Reversal also mirrors the seasonal phase; with no seasonal cycle the fit is exact.
    assert b == pytest.approx((-a[0], -a[1]), rel=1e-6, abs=1e-6)


@settings(max_examples=25, deadline=None)
@given(series_params, st.floats(0.01, 100.0))
def test_scaling_keeps_p_values(params: dict, k: float) -> None:  # type: ignore[type-arg]
    """Section 13.5: multiplying by k multiplies the slope by k and does not change p."""
    s, _ = synthetic_case(**params)
    a = analyze_series(s)
    b = analyze_series(_map(s, lambda v: v * k))
    for method in ("ols_ar1", "ols_ar1_annual", "mk_ar1"):
        ta, tb = a.test(method), b.test(method)
        assert ta is not None and tb is not None
        assert tb.p_value == pytest.approx(ta.p_value, rel=1e-6, abs=1e-12), method
