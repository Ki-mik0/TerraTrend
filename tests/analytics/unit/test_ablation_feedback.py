"""Stage A11: feedback loop of the advisory models (PLAN 11.3, 6.7, 13.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from earthtrend.analytics.ablation.feedback import (
    PredictionRecord,
    ece,
    from_ai_opinion,
    from_potential,
    monitor,
)
from earthtrend.analytics.models import AiOpinion

T0 = datetime(2026, 1, 1)


def _records(
    p: np.ndarray, y: np.ndarray, model: str = "m2_potential", version: str = "v1"
) -> list[PredictionRecord]:
    return [
        PredictionRecord(
            model=model,
            model_version=version,
            key=f"k{i}",
            p=float(pi),
            actual=bool(yi),
            at=T0 + timedelta(hours=i),
        )
        for i, (pi, yi) in enumerate(zip(p, y, strict=True))
    ]


def _calibrated(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    p = rng.beta(0.5, 0.5, n)
    return p, rng.random(n) < p


def test_calibrated_model_has_no_drift() -> None:
    p, y = _calibrated(2000)
    [r] = monitor(_records(p, y), window=1000)
    assert r.n == 1000 and r.n_total == 2000
    assert r.ece is not None and r.ece < 0.05
    assert r.brier is not None and r.baseline_brier is not None
    assert r.brier < r.baseline_brier
    assert r.codes == []
    assert r.window_end == T0 + timedelta(hours=1999)


def test_overconfident_model_drifts() -> None:
    p, y = _calibrated(1000, seed=1)
    [r] = monitor(_records(1 - p, y))  # anti-correlated hints
    assert "calibration_drift" in r.codes
    assert "brier_worse_than_baseline" in r.codes
    assert r.agreement is not None and r.agreement < 0.5


def test_too_few_records_suppresses_drift_codes() -> None:
    p, y = _calibrated(150, seed=2)
    [r] = monitor(_records(1 - p, y))
    assert r.codes == ["too_few_records"]
    assert r.ece is not None and r.ece > 0.05


def test_rolling_window_sees_only_recent_records() -> None:
    p, y = _calibrated(600, seed=3)
    good = _records(p[:300], y[:300])
    late = _records(1 - p[300:], y[300:])
    for i, r in enumerate(late):
        r.at = T0 + timedelta(days=30, hours=i)
    [full] = monitor(good + late, window=600)
    [recent] = monitor(good + late, window=250)
    assert full.agreement is not None and recent.agreement is not None
    assert recent.agreement < 0.4 < full.agreement
    assert recent.n == 250 and "calibration_drift" in recent.codes


def test_groups_by_model_and_version_with_external_baseline() -> None:
    p, y = _calibrated(400, seed=4)
    recs = (
        _records(p, y, version="v1")
        + _records(p, y, version="v2")
        + _records(p, y, model="m1_trendnet", version="m1-a")
    )
    reports = monitor(recs, baseline_rates={"m2_potential": 0.5})
    assert [(r.model, r.model_version) for r in reports] == [
        ("m1_trendnet", "m1-a"),
        ("m2_potential", "v1"),
        ("m2_potential", "v2"),
    ]
    assert reports[1].baseline_brier == pytest.approx(0.25)


def test_ece_matches_hand_computation() -> None:
    p = np.array([0.05, 0.05, 0.95, 0.95])
    y = np.array([False, True, True, True])
    # bin 0: |0.05 - 0.5| * 0.5, bin 9: |0.95 - 1.0| * 0.5
    assert ece(p, y) == pytest.approx(0.5 * 0.45 + 0.5 * 0.05)


def test_record_needs_a_prediction() -> None:
    with pytest.raises(ValidationError):
        PredictionRecord(model="m", model_version="v", key="k", actual=True, at=T0)
    with pytest.raises(ValidationError):
        PredictionRecord(model="m", model_version="v", key="k", p=1.5, actual=True, at=T0)


def test_class_agreement() -> None:
    r = PredictionRecord(
        model="m1_trendnet",
        model_version="v",
        key="k",
        predicted_class="step",
        actual=False,
        actual_class="step",
        at=T0,
    )
    assert r.agrees
    assert PredictionRecord(
        model="m", model_version="v", key="k", predicted_class="linear", actual=True, at=T0
    ).agrees


def test_adapters_for_m1_and_m2() -> None:
    m2 = from_potential(
        key="r/v/DJF", model_version="m2-1", p_significant=0.8, verdict="likely", at=T0
    )
    assert m2.actual is False and not m2.agrees

    op = AiOpinion(
        model_version="m1-1",
        class_probs={
            "no_trend": 0.1,
            "linear": 0.5,
            "step": 0.2,
            "accelerating": 0.1,
            "trend_plus_step": 0.1,
        },
        predicted_class="linear",
        slope_per_decade=0.2,
        slope_pi90=(0.1, 0.3),
        confidence="medium",
        agrees_with_statistics=True,
    )
    m1 = from_ai_opinion(op, key="case-1", verdict="proven", at=T0)
    assert m1.model == "m1_trendnet" and m1.p == pytest.approx(0.7)
    assert m1.actual and m1.agrees
    [rep] = monitor([m1])
    assert rep.agreement == 1.0 and rep.codes == ["too_few_records"]


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError):
        monitor([], window=0)
    assert monitor([]) == []
