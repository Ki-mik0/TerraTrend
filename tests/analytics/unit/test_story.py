"""Story Lens (section 10): process graph, related variables, patterns, facts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from earthtrend.analytics.models import AnalysisOptions, RegionalSeries
from earthtrend.analytics.simulate.synthetic import ar1_noise, default_meta
from earthtrend.analytics.story import (
    PATTERNS,
    ConceptTrend,
    PatternContext,
    build_story_facts,
    default_process_graph,
    lagged_correlation,
    load_process_graph,
    match_patterns,
    related_variables,
    story_lens,
)
from earthtrend.analytics.story.related import Detrended, detrended_anomalies

N_YEARS = 35
N = N_YEARS * 12
DATES = [date(1985 + i // 12, i % 12 + 1, 1) for i in range(N)]
T_DEC = (np.arange(N) + 0.5) / 120.0


def _make(concept: str, values: np.ndarray, region: str = "r1") -> RegionalSeries:
    meta = default_meta(variable_id=f"{concept}_ds", concept_id=concept, region_id=region)
    return RegionalSeries(meta=meta, dates=DATES, values=[float(v) for v in values])


def _shift(x: np.ndarray, lag: int) -> np.ndarray:
    """y(t) = x(t - lag) (y responds ``lag`` months after x); edges padded."""
    out = np.empty_like(x)
    out[lag:] = x[: x.size - lag]
    out[:lag] = x[0]
    return out


# ---------------------------------------------------------------- process graph


def test_catalog_graph_loads_and_is_consistent() -> None:
    g = load_process_graph()
    assert g.version == "processes_v1" and g.has(g.control_concept)
    concepts = {n.id for n in g.nodes}
    for p in PATTERNS:  # every concept the pattern library needs is in the graph
        for c in p.conditions:
            for o in c.options:
                assert o.concept in concepts, o.concept
    assert default_process_graph() is default_process_graph()


def test_neighbors_depth_sign_and_lag() -> None:
    g = load_process_graph()
    near = {p.concept_id: p for p in g.neighbors("precipitation", max_depth=2)}
    ndvi = near["ndvi"]
    assert ndvi.depth == 1 and ndvi.expected_sign == 1 and ndvi.lag_months == 1
    assert ndvi.mechanism_codes == ["water_supply_vegetation"]
    # precipitation -> soil_moisture (+, 0) <- air_temperature (-, 1): T leads by 1 month
    t = near["air_temperature"]
    assert t.depth == 2 and t.path == ["precipitation", "soil_moisture_surface", "air_temperature"]
    assert t.expected_sign == -1 and t.lag_months == -1
    assert all(p.depth <= 2 for p in near.values())
    back = {p.concept_id: p for p in g.neighbors("ndvi", max_depth=1)}
    assert back["precipitation"].lag_months == -1  # precipitation leads NDVI
    assert g.neighbors("unknown_concept") == []
    assert "precipitation" not in near


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ("  - {id: precipitation, group: water}\n", "duplicate node"),
        (
            "  - {source: ndvi, target: ghost, expected_sign: 1, lag_months: 0, "
            "mechanism_code: x}\n",
            "unknown node",
        ),
        (
            "  - {source: ndvi, target: ndvi, expected_sign: 1, lag_months: 0, "
            "mechanism_code: x}\n",
            "self-loop",
        ),
        (
            "  - {source: precipitation, target: ndvi, expected_sign: 1, lag_months: 0, "
            "mechanism_code: x}\n",
            "duplicate edge",
        ),
        (
            "  - {source: ndvi, target: precipitation, expected_sign: 1, lag_months: 0, "
            "mechanism_code: Bad Code}\n",
            "snake_case",
        ),
        (
            "  - {source: ndvi, target: precipitation, expected_sign: 2, lag_months: 0, "
            "mechanism_code: x}\n",
            "expected_sign",
        ),
        (
            "  - {source: ndvi, target: precipitation, expected_sign: 1, lag_months: 99, "
            "mechanism_code: x}\n",
            "lag_months",
        ),
    ],
)
def test_invalid_graph_rejected(tmp_path: Path, patch: str, message: str) -> None:
    text = load_process_graph.__globals__["DEFAULT_PATH"].read_text(encoding="utf-8")
    if "id:" in patch and "source" not in patch:
        text = text.replace("edges:\n", patch + "\nedges:\n", 1)
    else:
        text = text.rstrip("\n") + "\n" + patch
    p = tmp_path / "processes.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_process_graph(p)


def test_control_concept_must_exist(tmp_path: Path) -> None:
    text = load_process_graph.__globals__["DEFAULT_PATH"].read_text(encoding="utf-8")
    p = tmp_path / "g.yaml"
    p.write_text(text.replace("control_concept: air_temperature", "control_concept: x"))
    with pytest.raises(ValueError, match="control_concept"):
        load_process_graph(p)


# ---------------------------------------------------------------- correlations


def test_detrending_removes_spurious_correlation() -> None:
    rng = np.random.default_rng(0)
    a = 2.0 * T_DEC + ar1_noise(N, 0.3, 0.5, rng)
    b = 1.5 * T_DEC + ar1_noise(N, 0.3, 0.5, rng)
    assert np.corrcoef(a, b)[0, 1] > 0.5  # raw series: both trends -> spurious r
    opts = AnalysisOptions()
    n, r, p, n_eff, _, _ = lagged_correlation(
        detrended_anomalies(_make("x", a), opts), detrended_anomalies(_make("y", b), opts), 0
    )
    assert n == N and r is not None and p is not None and n_eff is not None
    assert abs(r) < 0.2  # vs > 0.5 before detrending


@pytest.mark.slow
@pytest.mark.parametrize("phi", [0.3, 0.7])
def test_correlation_false_alarm_rate(phi: float) -> None:
    """Independent trending AR(1) pairs: p < 0.05 in 3-7% (measured 2.5% / 4.75%, 400 runs)."""
    rng = np.random.default_rng(1)
    opts = AnalysisOptions()
    hits = 0
    runs = 400
    for _ in range(runs):
        a = 2.0 * T_DEC + ar1_noise(N, phi, 0.5, rng)
        b = 1.5 * T_DEC + ar1_noise(N, phi, 0.5, rng)
        res = lagged_correlation(
            detrended_anomalies(_make("x", a), opts), detrended_anomalies(_make("y", b), opts), 0
        )
        assert res[2] is not None
        hits += res[2] < 0.05
    assert 0.01 <= hits / runs <= 0.08


def test_lag_and_partial_correlation() -> None:
    rng = np.random.default_rng(1)
    temp = ar1_noise(N, 0.5, 1.0, rng)
    driver = ar1_noise(N, 0.3, 1.0, rng)
    resp = _shift(driver, 2) + 0.5 * rng.normal(size=N)
    d_driver = Detrended({i: float(v) for i, v in enumerate(driver)}, 0.3)
    d_resp = Detrended({i: float(v) for i, v in enumerate(resp)}, 0.3)
    _, r2, p2, _, _, _ = lagged_correlation(d_driver, d_resp, 2)
    _, r0, _, _, _, _ = lagged_correlation(d_driver, d_resp, 0)
    assert r2 is not None and r0 is not None and p2 is not None
    assert r2 > 0.8 and abs(r0) < 0.3 and p2 < 1e-6

    # both driven by temperature -> correlated, but not after controlling for it
    x = temp + 0.4 * rng.normal(size=N)
    y = temp + 0.4 * rng.normal(size=N)
    dx = Detrended({i: float(v) for i, v in enumerate(x)}, 0.4)
    dy = Detrended({i: float(v) for i, v in enumerate(y)}, 0.4)
    dt = Detrended({i: float(v) for i, v in enumerate(temp)}, 0.5)
    _, r, _, _, pr, pp = lagged_correlation(dx, dy, 0, dt)
    assert r is not None and r > 0.7
    assert pr is not None and pp is not None and abs(pr) < 0.15


def test_too_little_overlap_gives_none() -> None:
    a = Detrended({i: float(i % 7) for i in range(20)}, 0.0)
    assert lagged_correlation(a, a, 0)[1] is None


@pytest.fixture(scope="module")
def drying_region() -> dict[str, RegionalSeries]:
    """Warming, drying soils, rising ET, falling NDVI, flat precipitation."""
    rng = np.random.default_rng(7)
    temp_noise = ar1_noise(N, 0.4, 0.5, rng)
    temp = 0.6 * T_DEC + temp_noise
    precip = 3.0 + ar1_noise(N, 0.2, 0.6, rng)
    p_anom = precip - 3.0
    sm = -0.4 * T_DEC - 0.6 * _shift(temp_noise, 1) + 0.5 * p_anom + 0.2 * rng.normal(size=N)
    et = 0.3 * T_DEC + 0.5 * temp_noise + 0.3 * rng.normal(size=N)
    ndvi = -0.05 * T_DEC + 0.05 * _shift(sm, 1) + 0.03 * rng.normal(size=N)
    return {
        "air_temperature": _make("air_temperature", temp),
        "precipitation": _make("precipitation", precip),
        "soil_moisture_surface": _make("soil_moisture_surface", sm),
        "evapotranspiration": _make("evapotranspiration", et),
        "ndvi": _make("ndvi", ndvi),
        "other_region_sm": _make("soil_moisture_surface", sm, region="r2"),
        "unrelated": _make("urban_heat_contrast", rng.normal(size=N)),
    }


def test_related_variables_of_soil_moisture(drying_region: dict[str, RegionalSeries]) -> None:
    main = drying_region["soil_moisture_surface"]
    cands = [v for k, v in drying_region.items() if k != "soil_moisture_surface"]
    rel = related_variables(main, cands)
    by = {r.concept_id: r for r in rel}
    assert "urban_heat_contrast" not in by  # not within 2 edges
    assert all(r.dataset_id for r in rel) and len(by) == len(rel)
    t = by["air_temperature"]
    assert t.route.depth == 1 and t.route.expected_sign == -1
    assert t.lag_used_months == -1  # temperature leads soil moisture by a month
    assert t.corr is not None and t.corr < -0.3 and t.corr_consistency == "consistent"
    assert t.trend_consistency == "consistent"  # T up, SM down, edge sign -1
    assert t.controlled_for is None  # no partial correlation against itself
    p = by["precipitation"]
    assert p.corr is not None and p.corr > 0.3 and p.corr_consistency == "consistent"
    assert p.controlled_for == "air_temperature" and p.partial_corr is not None
    assert p.partial_corr > 0.3
    assert by["ndvi"].lag_used_months == 1
    assert [r.route.depth for r in rel] == sorted(r.route.depth for r in rel)


def test_related_in_a_season_uses_yearly_lags(drying_region: dict[str, RegionalSeries]) -> None:
    main = drying_region["soil_moisture_surface"]
    cands = [drying_region["air_temperature"], drying_region["ndvi"]]
    rel = related_variables(main, cands, options=AnalysisOptions(season="JJA"))
    assert all(r.season == "JJA" and r.lag_used_months % 12 == 0 for r in rel)
    assert all(r.n_overlap <= N_YEARS for r in rel)


# ---------------------------------------------------------------- patterns


def _ct(concept: str, direction: str, sig: bool = True, s: float = 0.8, season: str = "annual"):
    return ConceptTrend(
        concept_id=concept,
        direction=direction,  # type: ignore[arg-type]
        significant=sig,
        strength=s,
        season=season,  # type: ignore[arg-type]
    )


def test_aridification_confidence() -> None:
    trends = [
        _ct("air_temperature", "up", s=1.0),
        _ct("precipitation", "none", sig=False, s=0.1),  # flat is accepted
        _ct("soil_moisture_surface", "down", s=0.6),
        _ct("evapotranspiration", "up", s=0.8),
        _ct("ndvi", "down", s=0.4),  # the better option (ET) is used
    ]
    res = {m.code: m for m in match_patterns(trends)}
    m = res["aridification"]
    assert m.n_counted == 4
    assert m.confidence == pytest.approx((1.0 + 0.5 + 0.6 + 0.8) / 4)
    et = next(c for c in m.conditions if c.code == "et_up_or_ndvi_down")
    assert et.concept_used == "evapotranspiration"


def test_required_condition_missing_or_failed() -> None:
    assert "aridification" not in {m.code for m in match_patterns([_ct("air_temperature", "up")])}
    wet = [
        _ct("air_temperature", "up"),
        _ct("precipitation", "up"),
        _ct("soil_moisture_surface", "down"),
    ]
    assert "aridification" not in {m.code for m in match_patterns(wet)}


def test_optional_condition_without_data_not_counted() -> None:
    m = match_patterns([_ct("no2", "down", s=0.9)])
    clean = next(x for x in m if x.code == "cleaner_air")
    assert clean.n_counted == 1 and clean.confidence == pytest.approx(0.9)
    aod = next(c for c in clean.conditions if c.code == "aod_down")
    assert aod.met is None


def test_greening_needs_cold_region_for_warming_option() -> None:
    trends = [_ct("ndvi", "up"), _ct("air_temperature", "up")]
    assert "greening" not in {m.code for m in match_patterns(trends)}
    cold = match_patterns(trends, context=PatternContext(cold_region=True))
    assert "greening" in {m.code for m in cold}


def test_earlier_spring_uses_spring_temperature() -> None:
    base = [_ct("growing_season_length", "up"), _ct("snow_days", "down")]
    annual_t = [*base, _ct("air_temperature", "up")]
    assert "earlier_spring" not in {m.code for m in match_patterns(annual_t)}
    spring = [*base, _ct("air_temperature", "up", season="MAM")]
    assert "earlier_spring" in {m.code for m in match_patterns(spring)}


def test_single_condition_patterns() -> None:
    codes = {
        m.code
        for m in match_patterns(
            [
                _ct("sea_surface_temperature", "up"),
                _ct("urban_heat_contrast", "up"),
                _ct("air_temperature_upper", "up"),
                _ct("stratosphere_temperature", "down"),
                _ct("snow_water_equivalent", "down"),
                _ct("air_temperature", "up"),
            ]
        )
    }
    assert {
        "ocean_warming",
        "urban_heating",
        "troposphere_warming_stratosphere_cooling",
        "snow_retreat",
    } <= codes


# ---------------------------------------------------------------- facts


def test_story_lens_end_to_end(drying_region: dict[str, RegionalSeries]) -> None:
    main = drying_region["soil_moisture_surface"]
    cands = [v for k, v in drying_region.items() if k != "soil_moisture_surface"]
    facts = story_lens(main, cands)
    assert facts.main.concept_id == "soil_moisture_surface" and facts.main.direction == "decreasing"
    assert facts.graph_version == "processes_v1"
    assert facts.witnesses is not None and facts.witnesses.status == "na"
    assert facts.alibi is not None
    assert "aridification" in {p.code for p in facts.patterns}
    n = facts.numbers
    assert n["main.slope_per_decade"] == pytest.approx(facts.main.slope_per_decade, abs=1e-6)
    for rv in facts.related:
        if rv.corr is not None:
            assert n[f"related.{rv.variable_id}.corr"] == pytest.approx(rv.corr, abs=1e-6)
    for pm in facts.patterns:
        assert f"patterns.{pm.code}.confidence" in n
    assert all(np.isfinite(v) for v in n.values())


def test_build_story_facts_without_protocol(drying_region: dict[str, RegionalSeries]) -> None:
    from earthtrend.analytics import analyze_series

    tr = analyze_series(drying_region["air_temperature"])
    facts = build_story_facts(tr)
    assert facts.main.verdict == tr.verdict.code and facts.main.ruleset == tr.verdict.ruleset
    assert facts.alibi is None and facts.witnesses is None and facts.related == []
    assert facts.ai_opinion is None and facts.ai_status is None
    assert "main.p_mk" in facts.numbers
