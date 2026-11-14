"""Derived indicators (PLAN_ANALYTICS section 7) and the annual-series trend path."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from earthtrend.analytics.indicators import (
    INDICATORS,
    analyze_annual_series,
    compute_indicator,
    etccdi,
)
from earthtrend.analytics.simulate.synthetic import default_meta


def calendar(y0: int, y1: int) -> list[date]:
    d, out = date(y0, 1, 1), []
    while d.year <= y1:
        out.append(d)
        d += timedelta(days=1)
    return out


def test_frost_and_summer_days_count() -> None:
    dates = calendar(2001, 2002)
    tmin = np.full(len(dates), 5.0)
    tmin[:10] = -1.0  # 10 frost days in 2001
    tmin[365 : 365 + 3] = -0.5  # 3 in 2002
    years, fd = etccdi.frost_days(dates, tmin)
    assert years.tolist() == [2001, 2002]
    assert fd.tolist() == [10.0, 3.0]
    tmax = np.where(np.arange(len(dates)) % 2 == 0, 30.0, 20.0)
    _, su = etccdi.summer_days(dates, tmax)
    assert su.tolist() == [183.0, 182.0]  # 2001 has 365 days: 2002 starts on an odd index


def test_kelvin_is_rejected() -> None:
    dates = calendar(2001, 2001)
    with pytest.raises(ValueError, match="Kelvin"):
        etccdi.frost_days(dates, np.full(len(dates), 280.0))


def test_incomplete_calendar_is_rejected() -> None:
    dates = calendar(2001, 2001)
    del dates[10]
    with pytest.raises(ValueError, match="complete daily calendar"):
        etccdi.cdd(dates, np.zeros(len(dates)))


def test_year_with_too_many_gaps_is_nan() -> None:
    dates = calendar(2001, 2002)
    pr = np.zeros(len(dates))
    pr[365 : 365 + 100] = np.nan  # 2002 has < 80% valid days
    _, out = etccdi.cdd(dates, pr)
    assert out[0] == 365.0
    assert np.isnan(out[1])


def test_cdd_longest_dry_run_and_gap_breaks_it() -> None:
    dates = calendar(2001, 2001)
    pr = np.full(len(dates), 5.0)
    pr[100:120] = 0.2  # 20 dry days
    pr[200:230] = 0.0  # 30 dry days, broken by a gap at 215
    pr[215] = np.nan
    _, out = etccdi.cdd(dates, pr)
    assert out[0] == 20.0


def test_rx5day_maximum_window() -> None:
    dates = calendar(2001, 2001)
    pr = np.zeros(len(dates))
    pr[50:55] = [10, 20, 30, 20, 10]
    pr[300] = 85.0
    _, out = etccdi.rx5day(dates, pr)
    assert out[0] == 90.0


def test_r95ptot_share() -> None:
    dates = calendar(2001, 2002)
    pr = np.zeros(len(dates))
    pr[::10] = 2.0  # wet days of 2 mm
    pr[5] = 50.0  # one heavy day in 2001
    _, out = etccdi.r95ptot(dates, pr, base=(2001, 2002))
    wet_2001 = pr[:365][pr[:365] >= 1].sum()
    assert out[0] == pytest.approx(100 * 50.0 / wet_2001)
    assert out[1] == 0.0


def test_gsl_nh_and_sh() -> None:
    dates = calendar(2001, 2002)
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    # Warm between day 100 and day 280 every year.
    warm = (doy >= 100) & (doy < 280)
    t = np.where(warm, 15.0, -5.0)
    years, gsl = etccdi.growing_season_length(dates, t, lat=50.0)
    assert gsl[0] == pytest.approx(180.0)
    # Southern Hemisphere: warm season spans the new year.
    t_sh = np.where(warm, -5.0, 15.0)
    _, gsl_sh = etccdi.growing_season_length(dates, t_sh, lat=-40.0)
    # season year 2001: 1 Jul 2001 .. 30 Jun 2002; warm from day 280 of 2001 to day 100 of 2002
    expected = (date(2002, 4, 10) - date(2001, 10, 7)).days
    assert gsl_sh[0] == pytest.approx(expected, abs=1)
    assert np.isnan(gsl_sh[1])  # 2002 season runs past the data


def test_gsl_never_warm_is_zero() -> None:
    dates = calendar(2001, 2001)
    _, gsl = etccdi.growing_season_length(dates, np.full(len(dates), -3.0))
    assert gsl[0] == 0.0


def test_snow_days_and_percent_rejected() -> None:
    dates = calendar(2001, 2001)
    sc = np.zeros(len(dates))
    sc[:40] = 0.8
    sc[40:50] = 0.4
    _, out = etccdi.snow_days(dates, sc)
    assert out[0] == 40.0
    with pytest.raises(ValueError, match="fraction"):
        etccdi.snow_days(dates, sc * 100)


@pytest.mark.slow
def test_tx90p_bootstrap_removes_base_edge_jump() -> None:
    # 8 independent cells average out sampling noise (~13 s).
    rng = np.random.default_rng(0)
    dates = calendar(1981, 2010)
    x = rng.normal(0, 3, (len(dates), 8))
    years, plain = etccdi.tx90p(dates, x, base=(1981, 2000), bootstrap_in_base=False)
    _, boot = etccdi.tx90p(dates, x, base=(1981, 2000), bootstrap_in_base=True)
    ib = years <= 2000
    out_rate = plain[~ib].mean()
    assert out_rate == pytest.approx(10.0, abs=1.0)
    np.testing.assert_allclose(boot[~ib], plain[~ib])
    # Measured: plain in-base 9.99 vs out 10.35; bootstrap in-base 10.34.
    assert abs(boot[ib].mean() - out_rate) < 0.5 * abs(plain[ib].mean() - out_rate)


def test_tx90p_is_about_ten_percent_in_base() -> None:
    rng = np.random.default_rng(0)
    dates = calendar(1991, 2000)
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    tmax = 15 + 10 * np.sin(2 * np.pi * (doy - 100) / 365) + rng.normal(0, 3, len(dates))
    _, out = etccdi.tx90p(dates, tmax, base=(1991, 2000), bootstrap_in_base=False)
    assert out.mean() == pytest.approx(10.0, abs=1.0)


def test_nan_quantile_matches_numpy() -> None:
    rng = np.random.default_rng(9)
    x = rng.normal(size=(50, 7))
    x[rng.random(x.shape) < 0.2] = np.nan
    x[:, 3] = np.nan
    with np.errstate(all="ignore"), pytest.warns(RuntimeWarning):
        ref = np.nanpercentile(x, 90, axis=0)
    np.testing.assert_allclose(etccdi.nan_quantile(x, 0.9, axis=0), ref)


def test_tx90p_grid_matches_single_cell() -> None:
    rng = np.random.default_rng(1)
    dates = calendar(1991, 2000)
    cube = 20 + rng.normal(0, 3, (len(dates), 2, 3))
    _, grid = etccdi.tx90p(dates, cube, base=(1991, 1995))
    _, one = etccdi.tx90p(dates, cube[:, 1, 2], base=(1991, 1995))
    np.testing.assert_allclose(grid[:, 1, 2], one)


def test_registry_covers_section_7_and_dispatches() -> None:
    assert set(INDICATORS) == {"TX90p", "FD", "SU", "Rx5day", "CDD", "R95pTOT", "GSL", "SNOW_DAYS"}
    dates = calendar(2001, 2002)
    years, out = compute_indicator("FD", dates, np.full(len(dates), -1.0))
    assert out.tolist() == [365.0, 365.0]
    with pytest.raises(ValueError, match="base"):
        compute_indicator("TX90p", dates, np.zeros(len(dates)))
    with pytest.raises(KeyError):
        compute_indicator("XYZ", dates, np.zeros(len(dates)))


# ---------------------------------------------------------------- annual trend path


def test_annual_series_detects_trend() -> None:
    rng = np.random.default_rng(3)
    years = np.arange(1981, 2021)
    values = 30 + 0.8 * (years - 1981) + rng.normal(0, 2, years.size)  # +8 days/decade
    r = analyze_annual_series(years, values, default_meta(variable_id="SU", units="days"))
    assert r.verdict.code == "strong"
    assert r.direction == "increasing"
    assert r.primary_slope_per_decade == pytest.approx(8.0, abs=1.5)
    assert {t.method for t in r.tests} == {"ols_ar1_annual", "mk_ar1", "sen"}
    assert r.influence is not None
    assert r.summary_text_facts["frequency"] == "annual"
    assert r.series_out.dates[0] == date(1981, 7, 1)


def test_annual_series_no_trend_and_short_record() -> None:
    rng = np.random.default_rng(4)
    years = np.arange(1981, 2021)
    r = analyze_annual_series(years, rng.normal(0, 1, years.size), default_meta())
    assert r.verdict.code == "no_evidence"
    short = analyze_annual_series(years[:6], rng.normal(0, 1, 6), default_meta())
    assert short.verdict.code == "inadmissible"


def test_annual_series_gaps_and_period() -> None:
    years = np.arange(1981, 2021)
    noise = np.random.default_rng(7).normal(0, 1, years.size)
    vals: list[float | None] = [float(y - 1981 + e) for y, e in zip(years, noise, strict=True)]
    vals[5] = None
    r = analyze_annual_series(years, vals, default_meta(), options=None)
    assert r.n_used == 39
    from earthtrend.analytics.models import AnalysisOptions

    p = analyze_annual_series(years, vals, default_meta(), AnalysisOptions(period=(1990, 2010)))
    assert p.period_used == (date(1990, 7, 1), date(2010, 7, 1))


def test_annual_series_false_alarm_rate() -> None:
    rng = np.random.default_rng(5)
    years = np.arange(1981, 2021)
    hits = sum(
        analyze_annual_series(years, rng.normal(0, 1, years.size), default_meta()).verdict.code
        == "strong"
        for _ in range(200)
    )
    assert hits / 200 <= 0.08


def test_indicator_end_to_end_warming_increases_su() -> None:
    rng = np.random.default_rng(6)
    dates = calendar(1981, 2020)
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    yr = np.array([d.year for d in dates], dtype=float)
    tmax = (
        18
        + 10 * np.sin(2 * np.pi * (doy - 100) / 365)
        + 0.05 * (yr - 1981)
        + rng.normal(0, 3, len(dates))
    )
    years, su = compute_indicator("SU", dates, tmax)
    r = analyze_annual_series(years, su, default_meta(variable_id="SU", units="days"))
    assert r.direction == "increasing"
    assert r.verdict.code == "strong"
