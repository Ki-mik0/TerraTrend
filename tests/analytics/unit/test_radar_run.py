"""Radar stage 2, score, novelty, feeds, AI input and typology (sections 8.5, 9.2-9.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pytest

from earthtrend.analytics.models import AiOpinion, AnalysisOptions, Changepoint, RegionalSeries
from earthtrend.analytics.radar import (
    RadarCandidate,
    RadarEntry,
    RadarOptions,
    RadarSeries,
    apply_novelty,
    build_feeds,
    change_typology,
    run_radar,
    score_entries,
)
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_series


def _input(var: str, region: str, trend: float, seed: int, group: str | None = "g", **kw: object):
    meta = default_meta(
        variable_id=var, concept_id=var, region_id=region, region_area_km2=1e4 * (seed + 1)
    )
    s = synthetic_series(
        n_years=30,
        trend_per_decade=trend,
        noise_sd=0.4,
        ar1=0.3,
        seed=seed,
        meta=meta,
        **kw,  # type: ignore[arg-type]
    )
    return RadarSeries(series=s, region_group=group)


@pytest.fixture(scope="module")
def scene() -> list[RadarSeries]:
    out = []
    # t2m: warming in r0..r2, cooling in r3 (same group -> "opposite"), flat elsewhere
    for r, trend in enumerate([0.9, 0.8, 0.7, -0.8, 0.0, 0.0]):
        out.append(_input("t2m", f"r{r}", trend, seed=r))
    # precip: flat, low noise -> "stable"
    for r in range(6):
        out.append(_input("precip", f"r{r}", 0.0, seed=100 + r))
    return out


@pytest.fixture(scope="module")
def run(scene: list[RadarSeries]):
    return run_radar(scene, RadarOptions(seasons=["annual"], top_n=12, changepoints=False))


def test_run_without_ai(run) -> None:
    assert run.n_series == 12 and run.n_tested == 12
    assert len(run.entries) == 12
    assert run.feeds.ai_flagged == [] and run.ai_model_version is None and run.warnings == []
    assert all(e.ai_opinion is None for e in run.entries)
    scores = [e.radar_score for e in run.entries]
    assert scores == sorted(scores, reverse=True)
    strongest = set(run.feeds.strongest)
    assert {"t2m|r0|annual", "t2m|r1|annual", "t2m|r3|annual"} <= strongest
    assert not any(k.startswith("precip") for k in strongest)
    assert all(e.novelty == "new" for e in run.entries)
    for e in run.entries:
        for f in e.feeds:
            assert e.key in getattr(run.feeds, f)


def test_opposite_and_stable_feeds(run) -> None:
    assert "t2m|r3|annual" in run.feeds.opposite
    assert "t2m|r0|annual" in run.feeds.opposite
    e = run.entry("t2m|r3|annual")
    assert e is not None and "t2m|r0|annual" in e.opposite_of
    stable = run.feeds.stable
    assert stable and all(k.startswith("precip") for k in stable)


def test_no_group_means_no_opposite() -> None:
    items = [_input("t2m", "a", 0.9, 1, group=None), _input("t2m", "b", -0.9, 2, group=None)]
    res = run_radar(items, RadarOptions(seasons=["annual"], changepoints=False, typology=False))
    assert res.feeds.opposite == []


def test_novelty_against_previous(run, scene: list[RadarSeries]) -> None:
    prev = [e.model_copy(deep=True) for e in run.entries]
    by_key = {e.key: e for e in prev}
    by_key["t2m|r0|annual"].verdict = "likely"  # now stronger -> upgraded
    by_key["precip|r0|annual"].verdict = "strong"  # now no_evidence -> downgraded
    gone = prev[0].model_copy(update={"key": "t2m|zz|annual"})
    prev.append(gone)
    del by_key
    prev = [e for e in prev if e.key != "precip|r1|annual"]  # -> new
    res = run_radar(
        scene, RadarOptions(seasons=["annual"], top_n=12, changepoints=False), previous=prev
    )
    nov = {e.key: e.novelty for e in res.entries}
    assert nov["t2m|r0|annual"] == "upgraded"
    assert nov["precip|r0|annual"] == "downgraded"
    assert nov["precip|r1|annual"] == "new"
    assert nov["t2m|r1|annual"] == "unchanged"
    assert res.dropped == ["t2m|zz|annual"]


def _opinion(cls: str, slope: float = 0.5, conf: str = "high") -> AiOpinion:
    classes = ["no_trend", "linear", "step", "accelerating", "trend_plus_step"]
    probs = {c: (0.8 if c == cls else 0.05) for c in classes}
    return AiOpinion(
        model_version="trendnet_test_0",
        class_probs=probs,
        predicted_class=cls,
        slope_per_decade=slope,
        slope_pi90=(slope - 0.2, slope + 0.2),
        confidence=conf,  # type: ignore[arg-type]
        agrees_with_statistics=cls != "step",
    )


def test_ai_flagged_with_fake_detective(scene: list[RadarSeries]) -> None:
    def detective(series: Sequence[RegionalSeries], opts: AnalysisOptions) -> list[AiOpinion]:
        return [
            _opinion("step")
            if s.meta.region_id == "r1" and s.meta.variable_id == "t2m"
            else _opinion("linear", conf="low")
            for s in series
        ]

    res = run_radar(
        scene, RadarOptions(seasons=["annual"], top_n=12, changepoints=False), ai=detective
    )
    assert res.ai_model_version == "trendnet_test_0"
    assert res.feeds.ai_flagged == ["t2m|r1|annual"]
    c = next(c for c in res.candidates if c.key == "t2m|r1|annual")
    assert c.ai_disagrees and c.ai_class == "step" and c.ai_step_prob == pytest.approx(0.85)
    e = res.entry("t2m|r1|annual")
    assert e is not None and e.ai_opinion is not None and "ai_flagged" in e.feeds


def test_failing_or_wrong_ai_does_not_crash(scene: list[RadarSeries]) -> None:
    def broken(series: Sequence[RegionalSeries], opts: AnalysisOptions) -> list[AiOpinion]:
        raise RuntimeError("model file missing")

    def short(series: Sequence[RegionalSeries], opts: AnalysisOptions) -> list[AiOpinion | None]:
        return [None]

    opts = RadarOptions(seasons=["annual"], top_n=2, changepoints=False, typology=False)
    a = run_radar(scene, opts, ai=broken)
    assert a.warnings == ["ai_failed"] and a.feeds.ai_flagged == []
    b = run_radar(scene, opts, ai=short)
    assert b.warnings == ["ai_wrong_length"] and b.feeds.ai_flagged == []


def test_duplicate_inputs_rejected() -> None:
    a = _input("t2m", "r0", 0.5, 1)
    with pytest.raises(ValueError, match="duplicate"):
        run_radar([a, a])


def test_accelerating_feed() -> None:
    items = [_input("t2m", "acc", 1.0, 5, accel=0.5), _input("t2m", "lin", 0.6, 6)]
    res = run_radar(items, RadarOptions(seasons=["annual"], changepoints=False, typology=False))
    e = res.entry("t2m|acc|annual")
    assert e is not None and e.shape == "accelerating"
    assert "t2m|acc|annual" in res.feeds.accelerating
    assert "t2m|lin|annual" not in res.feeds.accelerating
    assert e.score_parts.get("accelerating") == 10.0


@pytest.mark.slow
def test_breakpoint_feed_with_beast() -> None:
    """A level shift 3 years before the end -> ``breakpoints`` (BEAST, ~0.3 s per case)."""
    items = [
        _input("t2m", "jump", 0.0, 7, step=(2007, 1.5)),
        _input("t2m", "flat", 0.0, 8),
    ]
    res = run_radar(items, RadarOptions(seasons=["annual"], typology=False))
    assert "t2m|jump|annual" in res.feeds.breakpoints
    assert "t2m|flat|annual" not in res.feeds.breakpoints
    e = res.entry("t2m|jump|annual")
    assert e is not None and e.recent_breakpoint is not None and e.new_breakpoint


# ---------------------------------------------------------------- unit: score, feeds


def _cand(key: str, q: float = 0.01, area: float | None = 1e4, **kw: object) -> RadarCandidate:
    var, region, season = key.split("|")
    return RadarCandidate(
        key=key,
        variable_id=var,
        concept_id=var,
        dataset_id="d",
        region_id=region,
        season=season,  # type: ignore[arg-type]
        region_area_km2=area,
        n_years=30,
        q_global=q,
        q_variable=q,
        **kw,  # type: ignore[arg-type]
    )


def _entry(key: str, verdict: str = "strong", strength: int = 80, **kw: object) -> RadarEntry:
    cand = kw.pop("candidate", None) or _cand(key)
    base: dict[str, object] = {
        "key": key,
        "candidate": cand,
        "verdict": verdict,
        "strength": strength,
        "direction": "increasing",
        "caveats": [],
        "items": {"statistics": "pass"},
        "primary_slope_per_decade": 0.5,
        "primary_ci95": (0.3, 0.7),
        "sigma_anom": 1.0,
        "snr": 0.5,
        "years_to_detect": 20.0,
        "years_to_detect_remaining": 0.0,
        "shape": "linear",
    }
    base.update(kw)
    return RadarEntry.model_validate(base)


def test_radar_score_formula() -> None:
    big = _entry("v|big|annual", strength=80, candidate=_cand("v|big|annual", q=0.0, area=1e6))
    small = _entry("v|small|annual", strength=80, candidate=_cand("v|small|annual", area=1e2))
    unknown = _entry("v|none|annual", strength=80, candidate=_cand("v|none|annual", area=None))
    split = _entry(
        "v|split|annual", strength=80, split_flag=True, candidate=_cand("v|split|annual", area=1e6)
    )
    entries = [big, small, unknown, split]
    score_entries(entries, RadarOptions())
    assert big.radar_score == pytest.approx(80.0)
    expected_small = 80 * 0.99 * np.log1p(1e2) / np.log1p(1e6)
    assert small.radar_score == pytest.approx(expected_small, rel=1e-4)
    # missing area -> median area term of the run
    terms = sorted([1.0, np.log1p(1e2) / np.log1p(1e6), 1.0])
    assert unknown.score_parts["area_term"] == pytest.approx(terms[1], rel=1e-4)
    assert split.score_parts["split"] == 10.0
    assert split.radar_score == pytest.approx(80 * 0.99 + 10.0, rel=1e-4)


def test_feed_rules_on_hand_made_entries() -> None:
    cp_recent = Changepoint(at=date(2019, 6, 1), probability=0.9, ci=None, jump=1.0, method="beast")
    entries = [
        _entry("v|almost|annual", verdict="suspicious", years_to_detect_remaining=4.0),
        _entry("v|far|annual", verdict="suspicious", years_to_detect_remaining=30.0),
        _entry("v|stable|annual", verdict="no_evidence", primary_ci95=(-0.1, 0.12)),
        _entry("v|wide|annual", verdict="no_evidence", primary_ci95=(-0.5, 0.6)),
        _entry("v|brk|annual", verdict="likely", recent_breakpoint=cp_recent),
        _entry(
            "v|ai|annual",
            ai_opinion=_opinion("trend_plus_step"),
        ),
        _entry("v|ai_quiet|annual", ai_opinion=_opinion("linear")),
    ]
    feeds = build_feeds(entries, [e.candidate for e in entries], RadarOptions())
    assert feeds.almost == ["v|almost|annual"]
    assert feeds.stable == ["v|stable|annual"]
    assert feeds.breakpoints == ["v|brk|annual"]
    assert feeds.ai_flagged == ["v|ai|annual"]
    assert set(feeds.strongest) == {"v|ai|annual", "v|ai_quiet|annual"}


def test_new_breakpoint_cleared_when_seen_before() -> None:
    cp = Changepoint(at=date(2019, 6, 1), probability=0.9, ci=None, jump=1.0, method="beast")
    now = _entry("v|a|annual", recent_breakpoint=cp, new_breakpoint=True, changepoints=[cp])
    old_cp = cp.model_copy(update={"at": date(2019, 1, 1)})
    prev = _entry("v|a|annual", changepoints=[old_cp])
    apply_novelty([now], [prev])
    assert now.new_breakpoint is False and now.novelty == "unchanged"


# ---------------------------------------------------------------- typology (8.5)


def test_typology_recovers_sign_patterns() -> None:
    rng = np.random.default_rng(0)
    patterns = np.array([[1, -1, 0], [1, 1, 0], [-1, 0, 1], [0, 0, 0]], dtype=float)
    x = np.vstack([p * 0.8 + rng.normal(0, 0.08, (15, 3)) for p in patterns])
    units = [f"u{i}" for i in range(x.shape[0])]
    res = change_typology(x, ["t2m", "precip", "ndvi"], units, seed=1)
    assert res is not None and res.method == "kmeans" and res.k == 4
    assert res.silhouette is not None and res.silhouette > 0.7
    codes = {c.code for c in res.clusters}
    assert codes == {"t2m+|precip-", "t2m+|precip+", "t2m-|ndvi+", "no_change"}
    for g in range(4):
        labels = {res.assignments[f"u{i}"] for i in range(g * 15, (g + 1) * 15)}
        assert len(labels) == 1
    again = change_typology(x, ["t2m", "precip", "ndvi"], units, seed=1)
    assert again == res  # deterministic


def test_typology_hdbscan_request_falls_back_or_runs() -> None:
    rng = np.random.default_rng(2)
    x = np.vstack([p + rng.normal(0, 0.05, (20, 2)) for p in ([1, 1], [-1, 1], [1, -1])])
    res = change_typology(x, ["a", "b"], [str(i) for i in range(60)], method="hdbscan")
    assert res is not None and res.method in ("kmeans", "hdbscan")


def test_typology_too_small_returns_none() -> None:
    assert change_typology(np.zeros((3, 2)), ["a", "b"], ["x", "y", "z"]) is None


def test_run_typology_from_scan(run) -> None:
    # 6 regions < MIN_UNITS: no typology rather than a meaningless one
    assert run.typology is None
