from datetime import date

import numpy as np
import pytest

from earthtrend.analytics.evidence.alibi import alibi, alibi_caveats, alibi_status
from earthtrend.analytics.evidence.quality import artifact_flags, long_memory, quality_status
from earthtrend.analytics.evidence.triangle import trend_triangle, triangle_status
from earthtrend.analytics.evidence.witnesses import compare_witnesses, witnesses_status
from earthtrend.analytics.models import ClimateIndex, QualityFlag, SensorEvent
from earthtrend.analytics.preprocess.aggregate import decimal_year, split_dates
from earthtrend.analytics.simulate.synthetic import (
    ar1_noise,
    default_meta,
    fractional_noise,
    synthetic_case,
)
from earthtrend.analytics.trend.jackknife import jackknife
from earthtrend.analytics.trend.seasonal_mk import seasonal_mk

YEARS = np.arange(1981, 2026)


# ---------------------------------------------------------------- jackknife


def test_jackknife_finds_a_dominating_year() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(0, 0.3, YEARS.size)
    a[-1] += 6.0  # one extreme last year creates the "trend"
    jk = jackknife(YEARS, a)
    assert jk is not None
    if jk.full_p_mk < 0.05:
        assert jk.influential
        assert 2025 in (jk.most_influential_year, jk.significance_lost_year)


def test_jackknife_steady_trend_is_not_influential() -> None:
    rng = np.random.default_rng(1)
    a = 0.05 * (YEARS - 1981) + rng.normal(0, 0.2, YEARS.size)
    jk = jackknife(YEARS, a)
    assert jk is not None and not jk.influential
    assert len(jk.years) == YEARS.size
    assert jk.max_rel_change < 0.3


def test_jackknife_ignores_flat_series() -> None:
    a = np.random.default_rng(2).normal(0, 1, YEARS.size)
    jk = jackknife(YEARS, a)
    assert jk is not None and (jk.full_p_mk >= 0.05) <= (not jk.influential)


# ---------------------------------------------------------------- seasonal MK


def test_seasonal_mk_detects_trend_in_raw_monthly_data() -> None:
    s, _ = synthetic_case(n_years=30, seasonal_amplitude=10, slope_per_decade=1.0, seed=1)
    _, months = split_dates(s.dates)
    v = np.array(s.values, dtype=float)
    res = seasonal_mk(v, months)
    assert res is not None and res[0] < 1e-6 and res[1] > 0
    assert seasonal_mk(v[:24], months[:24]) is None


# ---------------------------------------------------------------- triangle


def test_triangle_steady_trend_passes() -> None:
    rng = np.random.default_rng(3)
    a = 0.04 * (YEARS - 1981) + rng.normal(0, 0.15, YEARS.size)
    tri = trend_triangle(YEARS, a, 1)
    assert tri is not None and triangle_status(tri) == "pass"
    assert tri.min_window == 15
    assert tri.slope_per_decade[0][14] is not None and tri.slope_per_decade[0][13] is None


def test_triangle_recent_jump_is_period_sensitive() -> None:
    rng = np.random.default_rng(4)
    a = rng.normal(0, 0.3, YEARS.size)
    a[-6:] += 2.0  # flat, then a jump in the last years
    tri = trend_triangle(YEARS, a, 1)
    assert triangle_status(tri) in ("partial", "fail")


def test_triangle_needs_enough_years() -> None:
    assert trend_triangle(YEARS[:8], np.arange(8.0), 1) is None
    assert triangle_status(None) == "na"
    assert trend_triangle(YEARS[:20], np.arange(20.0), 1).min_window == 10  # type: ignore[union-attr]


# ---------------------------------------------------------------- witnesses


def _ds(name: str, slope: float, seed: int, n_years: int = 40, start: int = 1981):
    return synthetic_case(
        meta=default_meta(dataset_id=name),
        n_years=n_years,
        start_year=start,
        slope_per_decade=slope,
        phi=0.3,
        sigma=0.5,
        seed=seed,
    )[0]


def test_witnesses_agree() -> None:
    res = compare_witnesses(_ds("a", 1.0, 1), [_ds("b", 1.0, 2, start=1985, n_years=40)])
    assert res is not None
    assert res.common_period == (date(1985, 1, 1), date(2020, 12, 1))
    assert witnesses_status(res) == "pass"
    assert len(res.pairs) == 1 and not res.pairs[0].diverge


def test_witnesses_opposite_signs_fail() -> None:
    res = compare_witnesses(_ds("a", 1.0, 1), [_ds("b", -1.0, 2)])
    assert witnesses_status(res) == "fail"


def test_witnesses_rate_disagreement_is_partial() -> None:
    res = compare_witnesses(_ds("a", 1.0, 1), [_ds("b", 2.5, 2)])
    assert res is not None and res.pairs[0].diverge
    assert witnesses_status(res) == "partial"


def test_no_witnesses_is_na() -> None:
    assert compare_witnesses(_ds("a", 1.0, 1), []) is None
    assert witnesses_status(None) == "na"


# ---------------------------------------------------------------- alibi


def _series_with_index(trend: float, coef: float, lag: int, index_trend: float = 0.0):
    rng = np.random.default_rng(7)
    n = 45 * 12
    dates = [date(1981 + i // 12, i % 12 + 1, 1) for i in range(n + 12)]
    idx = ar1_noise(n + 12, 0.8, 0.6, rng) + index_trend * np.arange(n + 12) / 120
    years, months = split_dates(dates[12:])
    t = decimal_year(years, months)
    anom = trend / 10 * (t - t[0]) + coef * idx[12 - lag : 12 - lag + n] + rng.normal(0, 0.3, n)
    index = ClimateIndex(name="nino34", dates=dates, values=idx.tolist())
    return t, anom, years, months, dates[12:], index


def test_alibi_finds_lag_and_keeps_trend() -> None:
    t, anom, years, months, dates, index = _series_with_index(trend=0.3, coef=0.8, lag=4)
    res = alibi(t, anom, years, months, dates, [index])
    assert res is not None
    assert [(x.index, x.lag_months) for x in res.terms] == [("nino34", 4)]
    assert res.terms[0].coefficient == pytest.approx(0.8, abs=0.05)
    assert res.b_adjusted_per_decade == pytest.approx(0.3, abs=0.05)
    assert res.partial_r2 > 0.5
    assert alibi_status(res) == "pass"


def test_alibi_rejects_an_unrelated_index() -> None:
    t, anom, years, months, dates, _ = _series_with_index(trend=0.3, coef=0.0, lag=0)
    rng = np.random.default_rng(99)
    noise = ClimateIndex(name="nao", dates=dates, values=rng.normal(size=len(dates)).tolist())
    res = alibi(t, anom, years, months, dates, [noise])
    assert res is not None and res.terms == [] and res.rejected == ["nao"]
    assert res.b_adjusted_per_decade == pytest.approx(res.b_raw_per_decade)


def test_trend_explained_by_index() -> None:
    # No own trend: the index itself trends and drives the series.
    t, anom, years, months, dates, index = _series_with_index(
        trend=0.0, coef=1.0, lag=0, index_trend=0.5
    )
    res = alibi(t, anom, years, months, dates, [index])
    status = alibi_status(res)
    assert status in ("partial", "fail")
    cav = alibi_caveats(res, status)
    assert "index_trend_overlap" in cav
    if status == "fail":
        assert "explained_by_enso" in cav


def test_alibi_without_indices_is_na() -> None:
    assert alibi(np.arange(10.0), np.arange(10.0), YEARS[:10], YEARS[:10], [], []) is None
    assert alibi_status(None) == "na"


# ---------------------------------------------------------------- quality


def test_long_memory_detects_extra_structure_only() -> None:
    rng = np.random.default_rng(5)
    n = 528
    false_hits = sum(long_memory(ar1_noise(n, 0.5, 1.0, rng))[0] for _ in range(100))
    assert false_hits <= 5  # ~1% expected at p < 0.01; measured 0/100
    # Genuine long memory (ARFIMA d = 0.4): measured detection ~88%.
    hits = sum(long_memory(fractional_noise(n, 0.4, rng))[0] for _ in range(30))
    assert hits >= 18


def test_artifact_flags() -> None:
    period = (date(1981, 1, 1), date(2020, 12, 1))
    ev = [SensorEvent(date=date(2002, 5, 1), code="aqua_launch")]
    mid = artifact_flags([date(2002, 9, 1)], ev, period)
    assert [f.code for f in mid] == ["possible_artifact"]
    assert artifact_flags([date(2004, 1, 1)], ev, period) == []
    edge = artifact_flags(
        [date(1981, 6, 1)], [SensorEvent(date=date(1981, 3, 1), code="x")], period
    )
    assert [f.code for f in edge] == ["possible_artifact_edge"]


@pytest.mark.parametrize(
    ("codes", "status"),
    [
        ([], "pass"),
        (["outliers"], "partial"),
        (["outliers", "long_memory"], "partial"),
        (["outliers", "long_memory", "low_n_eff"], "fail"),
        (["many_gaps"], "fail"),
        (["possible_artifact"], "fail"),
        (["possible_artifact_edge"], "partial"),
    ],
)
def test_quality_status(codes: list[str], status: str) -> None:
    assert quality_status([QualityFlag(code=c) for c in codes]) == status
