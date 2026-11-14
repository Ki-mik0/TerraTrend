"""Monte-Carlo checks of the statistical core on series with known truth.

Measured on the reference implementation (40 years monthly, sigma=1, 400 runs):
  phi | OLS n_eff FA | MK-AR1 FA | naive OLS FA | Sen CI coverage | OLS CI coverage
  0.0 |    4.3%      |   4.5%    |    4.5%      |      91%        |      93%
  0.6 |    5.2%      |   5.8%    |   35.0%      |      91%        |      92%
  0.8 |    4.8%      |   6.5%    |   54.5%      |      90%        |      92%
The CIs under-cover slightly (sample r1 is biased low); thresholds below are set from
these numbers with Monte-Carlo slack, not from the nominal 95%.
"""

from dataclasses import dataclass

import numpy as np
import pytest

from earthtrend.analytics import AnalysisOptions, analyze_series
from earthtrend.analytics.preprocess.aggregate import decimal_year, split_dates
from earthtrend.analytics.simulate.synthetic import synthetic_case
from earthtrend.analytics.trend.ols import ols_ar1

TRUE_SLOPE = 0.5  # per decade
# Only the core tests matter here; skip the spline and per-month extras for speed.
CORE = AnalysisOptions(nonlinear=False, seasonal_breakdown=False)


@dataclass
class Rates:
    sen_coverage: float
    fa_ols: float
    fa_mk: float
    fa_naive: float


def _run(phi: float, runs: int) -> Rates:
    cov = fa_ols = fa_mk = fa_naive = 0
    for seed in range(runs):
        s, _ = synthetic_case(n_years=40, slope_per_decade=TRUE_SLOPE, phi=phi, seed=seed)
        sen = analyze_series(s, CORE).test("sen")
        assert sen is not None and sen.ci95 is not None
        cov += sen.ci95[0] <= TRUE_SLOPE <= sen.ci95[1]

        s0, _ = synthetic_case(n_years=40, slope_per_decade=0.0, phi=phi, seed=100_000 + seed)
        r0 = analyze_series(s0, CORE)
        ols, mk = r0.test("ols_ar1"), r0.test("mk_ar1")
        assert ols is not None and mk is not None
        fa_ols += ols.p_value is not None and ols.p_value < 0.05
        fa_mk += mk.p_value is not None and mk.p_value < 0.05
        y, m = split_dates(s0.dates)
        anom = np.array([np.nan if v is None else v for v in r0.series_out.anomalies])
        fit = ols_ar1(decimal_year(y, m), anom)
        assert fit is not None
        fa_naive += fit.p_value_naive < 0.05
    return Rates(cov / runs, fa_ols / runs, fa_mk / runs, fa_naive / runs)


def test_fast_sanity_phi_06() -> None:
    r = _run(0.6, 60)
    assert r.sen_coverage >= 0.78
    assert r.fa_ols <= 0.15
    assert r.fa_mk <= 0.15
    assert r.fa_naive >= 0.2  # documents why n_eff exists


@pytest.mark.slow
@pytest.mark.parametrize("phi", [0.0, 0.3, 0.6, 0.8])
def test_false_alarms_and_coverage(phi: float) -> None:
    r = _run(phi, 400)
    assert 0.025 <= r.fa_ols <= 0.075
    assert 0.025 <= r.fa_mk <= 0.085
    assert r.sen_coverage >= 0.87
    if phi >= 0.3:
        assert r.fa_naive > 2 * r.fa_ols
