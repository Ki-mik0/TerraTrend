"""Radar stage 1 (section 9.2): agreement with the series core, FDR, speed."""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pytest

from earthtrend.analytics.analyze import prepare_series
from earthtrend.analytics.models import AnalysisOptions, RegionalSeries
from earthtrend.analytics.preprocess.aggregate import annual_means, split_dates
from earthtrend.analytics.radar import RadarOptions, RadarSeries, scan_stage1, select_top
from earthtrend.analytics.radar.scan import yearly_block
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_series
from earthtrend.analytics.spatial.fdr import benjamini_hochberg
from earthtrend.analytics.trend.mann_kendall import mk_ar1
from earthtrend.analytics.trend.sen import sen_slope


def _series(i: int, trend: float, *, gaps: float = 0.0, log: bool = False) -> RegionalSeries:
    meta = default_meta(
        variable_id=f"v{i % 3}",
        region_id=f"r{i}",
        transform="log" if log else "none",
    )
    s = synthetic_series(
        n_years=30,
        trend_per_decade=trend,
        noise_sd=0.5,
        ar1=0.4,
        gaps=gaps,
        seed=i,
        base=10.0 if log else 0.0,
        meta=meta,
    )
    return s


@pytest.fixture(scope="module")
def mixed() -> list[RegionalSeries]:
    out = [_series(i, t) for i, t in enumerate([0.6, -0.4, 0.0, 0.2, 0.0, -0.8])]
    out.append(_series(6, 0.3, gaps=0.08))  # monthly gaps -> some invalid years
    out.append(_series(7, 0.1, log=True))
    return out


@pytest.mark.parametrize("season", ["annual", "DJF", "MAM", "JJA", "SON"])
@pytest.mark.parametrize("period", [None, (1985, 2008)])
def test_yearly_block_matches_series_core(
    mixed: list[RegionalSeries], season: str, period: tuple[int, int] | None
) -> None:
    rows = list(range(len(mixed)))
    blk = yearly_block(mixed, rows, season, period, (1990, 2005))  # type: ignore[arg-type]
    opts = AnalysisOptions(season=season, period=period, baseline=(1990, 2005))  # type: ignore[arg-type]
    for i, s in enumerate(mixed):
        p = prepare_series(s, opts)
        if season == "annual":
            y, m = split_dates(p.dates)
            years, vals = annual_means(p.anom, y, m)
        else:
            years, vals = split_dates(p.dates)[0], p.anom
        fin = np.isfinite(vals)
        got = dict(zip(blk.years.tolist(), blk.values[i].tolist(), strict=True))
        for yr, v, ok in zip(years.tolist(), vals.tolist(), fin.tolist(), strict=True):
            if ok:
                assert got[yr] == pytest.approx(v, abs=1e-12)
            else:
                assert not np.isfinite(got.get(yr, np.nan))
        assert blk.sigma[i] == pytest.approx(float(np.nanstd(p.anom, ddof=1)), rel=1e-12)


def test_kernel_matches_mk_and_sen(mixed: list[RegionalSeries]) -> None:
    inputs = [RadarSeries(series=s) for s in mixed]
    cands, _, _ = scan_stage1(inputs, RadarOptions(seasons=["annual", "JJA"]))
    by_key = {c.key: c for c in cands}
    for season in ("annual", "JJA"):
        blk = yearly_block(mixed, list(range(len(mixed))), season)  # type: ignore[arg-type]
        for i, s in enumerate(mixed):
            y = blk.values[i]
            mk = mk_ar1(y)
            assert mk is not None
            sen = sen_slope(blk.years.astype(float), y, mk.var_s)
            assert sen is not None
            c = by_key[f"{s.meta.variable_id}|{s.meta.region_id}|{season}"]
            assert c.z_mk == pytest.approx(mk.z, rel=1e-9, abs=1e-12)
            assert c.p_mk == pytest.approx(mk.p_value, rel=1e-9, abs=1e-12)
            assert c.slope_per_decade == pytest.approx(sen.slope * 10, rel=1e-9, abs=1e-12)
            assert c.ci95 is not None
            assert c.ci95[0] == pytest.approx(sen.ci95[0] * 10, rel=1e-9, abs=1e-12)
            assert c.ci95[1] == pytest.approx(sen.ci95[1] * 10, rel=1e-9, abs=1e-12)
            assert c.n_years == mk.n


def test_fdr_within_variable_and_global(mixed: list[RegionalSeries]) -> None:
    inputs = [RadarSeries(series=s) for s in mixed]
    cands, _, _ = scan_stage1(inputs, RadarOptions())
    tested = [c for c in cands if c.p_mk is not None]
    p = np.array([c.p_mk for c in tested])
    sig, q, _ = benjamini_hochberg(p, 0.10)
    for c, qq, ss in zip(tested, q, sig, strict=True):
        assert c.q_global == pytest.approx(qq)
        assert c.sig_global == bool(ss)
    for var in {c.variable_id for c in tested}:
        sub = [c for c in tested if c.variable_id == var]
        _, qv, _ = benjamini_hochberg(np.array([c.p_mk for c in sub]), 0.10)
        assert [c.q_variable for c in sub] == pytest.approx(qv.tolist())


def test_short_records_are_skipped_not_tested() -> None:
    short = synthetic_series(n_years=6, seed=1, meta=default_meta(region_id="short"))
    ok = synthetic_series(n_years=25, seed=2, meta=default_meta(region_id="ok"))
    cands, _, _ = scan_stage1([RadarSeries(series=short), RadarSeries(series=ok)])
    for c in cands:
        if c.region_id == "short":
            assert c.skipped == "short_record" and c.p_mk is None and c.q_global is None
        else:
            assert c.skipped is None and c.p_mk is not None
    assert all(c.region_id == "ok" for c in select_top(cands, 100))


def test_stage1_finds_planted_trends() -> None:
    inputs = []
    for r in range(40):
        trend = 0.8 if r < 10 else 0.0
        meta = default_meta(variable_id="t2m", region_id=f"r{r}")
        s = synthetic_series(n_years=35, trend_per_decade=trend, noise_sd=0.4, ar1=0.3, seed=r)
        inputs.append(RadarSeries(series=s.model_copy(update={"meta": meta})))
    cands, _, _ = scan_stage1(inputs, RadarOptions(seasons=["annual"]))
    hits = {c.region_id for c in cands if c.sig_variable}
    assert {f"r{r}" for r in range(10)} <= hits
    false = hits - {f"r{r}" for r in range(10)}
    assert len(false) <= 3
    top = select_top(cands, 10)
    assert {c.region_id for c in top} == {f"r{r}" for r in range(10)}


def _bulk_inputs(n: int, n_years: int = 40) -> list[RadarSeries]:
    rng = np.random.default_rng(0)
    t = n_years * 12
    dates = [date(1981 + i // 12, i % 12 + 1, 1) for i in range(t)]
    x = rng.normal(size=(n, t)) + 3 * np.sin(np.arange(t) * 2 * np.pi / 12)
    x[: n // 10] += np.linspace(0, 2.0, t)  # 10% with a trend
    return [
        RadarSeries(
            series=RegionalSeries(
                meta=default_meta(variable_id=f"v{i % 20}", region_id=f"r{i // 20}"),
                dates=dates,
                values=x[i].tolist(),
            )
        )
        for i in range(n)
    ]


def test_stage1_speed_small() -> None:
    inputs = _bulk_inputs(400)
    scan_stage1(inputs[:5])  # numba compile / cache load
    t0 = time.perf_counter()
    cands, _, _ = scan_stage1(inputs)
    dt = time.perf_counter() - t0
    assert len(cands) == 2000
    assert dt < 5.0  # measured ~0.3 s (2000 series-seasons, 40 years)


@pytest.mark.slow
def test_stage1_speed_large() -> None:
    """10k series x 5 seasons = 50k combinations; measured ~7 s (~0.14 ms each)."""
    inputs = _bulk_inputs(10_000)
    scan_stage1(inputs[:5])
    t0 = time.perf_counter()
    cands, _, _ = scan_stage1(inputs)
    dt = time.perf_counter() - t0
    print(f"radar stage 1: {len(cands)} combinations in {dt:.2f} s")
    assert len(cands) == 50_000
    assert dt < 60.0
