import time
from datetime import date

import numpy as np
import pytest

from earthtrend.analytics import (
    AnalysisOptions,
    ClimateIndex,
    EvidenceProtocol,
    SensorEvent,
    SplitResult,
    build_protocol,
)
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_case

KEYS = ["statistics", "magnitude", "witnesses", "robustness", "alibi", "quality"]


def _warming(seed: int = 1, name: str = "primary", **kw: object):
    params: dict[str, object] = dict(
        n_years=45, base=260.0, seasonal_amplitude=15.0, slope_per_decade=0.7, phi=0.5, seed=seed
    )
    params.update(kw)
    return synthetic_case(meta=default_meta(dataset_id=name), **params)[0]


def _enso(dates: list[date]) -> ClimateIndex:
    rng = np.random.default_rng(0)
    return ClimateIndex(name="nino34", dates=dates, values=rng.normal(size=len(dates)).tolist())


def test_clear_case_with_witness_and_alibi_is_proven() -> None:
    s = _warming()
    pr = build_protocol(s, witnesses=[_warming(2, "witness")], indices=[_enso(s.dates)])
    assert [i.key for i in pr.items] == KEYS
    assert pr.verdict == "proven" and pr.direction == "increasing"
    assert pr.strength == 100 and pr.ruleset == "verdict_rules_v1"
    assert not any(i.advisory for i in pr.items)


def test_single_dataset_without_alibi_can_be_strong_not_proven() -> None:
    pr = build_protocol(_warming())
    assert pr.item("witnesses").status == "na"  # type: ignore[union-attr]
    assert pr.item("alibi").status == "na"  # type: ignore[union-attr]
    assert pr.verdict == "strong"


def test_no_trend_is_no_evidence() -> None:
    s, _ = synthetic_case(n_years=45, slope_per_decade=0.0, phi=0.5, seed=3)
    pr = build_protocol(s)
    assert pr.verdict == "no_evidence" and pr.direction == "none"


def test_short_record_is_inadmissible() -> None:
    s, _ = synthetic_case(n_years=7, slope_per_decade=3.0, seed=1)
    pr = build_protocol(s)
    assert pr.verdict == "inadmissible" and pr.strength == 0
    assert "short_record" in pr.caveats


def test_poor_coverage_makes_a_clear_trend_suspicious() -> None:
    s = _warming().model_copy(update={"stable_fraction": 0.3})
    pr = build_protocol(s)
    assert pr.item("quality").status == "fail"  # type: ignore[union-attr]
    assert pr.verdict == "suspicious"
    assert "low_stable_coverage" in pr.caveats


def test_sensor_artifact_mid_series() -> None:
    pr = build_protocol(
        _warming(),
        changepoints=[date(2002, 8, 1)],
        sensor_events=[SensorEvent(date=date(2002, 5, 1), code="aqua_launch")],
    )
    assert "possible_artifact" in pr.caveats
    assert pr.verdict == "suspicious"


def test_disagreeing_witness() -> None:
    pr = build_protocol(_warming(), witnesses=[_warming(2, "w", slope_per_decade=-0.7)])
    assert pr.item("witnesses").status == "fail"  # type: ignore[union-attr]
    assert "witnesses_disagree" in pr.caveats
    assert pr.verdict == "likely"


def test_split_region_caveat() -> None:
    split = SplitResult(sig_pos=0.4, sig_neg=0.2, nonsig=0.4, split_flag=True)
    assert "split_region" in build_protocol(_warming(), split=split).caveats


def test_seasonal_case() -> None:
    pr = build_protocol(_warming(), AnalysisOptions(season="JJA"))
    assert pr.item("alibi").status == "na"  # type: ignore[union-attr]
    assert pr.verdict in ("proven", "strong", "likely")


def test_skewed_variable_decided_by_mk() -> None:
    s = _warming().model_copy(update={"meta": default_meta(distribution="skewed")})
    pr = build_protocol(s)
    assert pr.item("statistics").details["decided_by"] == "mk+seasonal_mk"  # type: ignore[union-attr]


def test_json_round_trip_and_speed() -> None:
    s = _warming()
    kw = {"witnesses": [_warming(2, "w")], "indices": [_enso(s.dates)]}
    build_protocol(s, **kw)  # type: ignore[arg-type]
    t0 = time.perf_counter()
    pr = build_protocol(s, **kw)  # type: ignore[arg-type]
    elapsed = time.perf_counter() - t0
    assert EvidenceProtocol.model_validate_json(pr.model_dump_json()) == pr
    assert elapsed < 0.5  # plan target 300 ms; CI machines get headroom


@pytest.mark.slow
def test_false_strong_rate_on_null_series() -> None:
    """Stage 4 calibrates thresholds; this only guards against a gross regression."""
    bad = 0
    runs = 200
    for seed in range(runs):
        s, _ = synthetic_case(n_years=40, slope_per_decade=0.0, phi=0.5, seed=50_000 + seed)
        bad += build_protocol(s).verdict in ("proven", "strong")
    assert bad / runs <= 0.05
