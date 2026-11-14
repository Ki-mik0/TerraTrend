"""M1 TrendNet: data generator, advisory integration, and (with torch) model / ONNX checks."""

from pathlib import Path

import numpy as np
import pytest

from earthtrend.analytics import AiOpinion, build_protocol
from earthtrend.analytics.ml import trendnet as rt
from earthtrend.analytics.simulate.synthetic import synthetic_case
from earthtrend.analytics.training.trendnet import data as tdata

# ---------------------------------------------------------------- data generator


def test_examples_are_deterministic_and_well_formed() -> None:
    a, b = tdata.make_example("val", 3), tdata.make_example("val", 3)
    np.testing.assert_array_equal(a.features, b.features)
    assert a.features.shape == (tdata.N_CHANNELS, tdata.MAX_LEN)
    n = int(a.mask.sum())
    assert n == a.n_years * 12 and tdata.MIN_YEARS <= a.n_years <= tdata.MAX_YEARS
    assert np.all(a.features[:, n:] == 0)
    assert a.features[4, n - 1] == pytest.approx(1.0)


def test_split_families_are_disjoint() -> None:
    train = {tdata.make_example("train", i).family for i in range(60)}
    newv = {tdata.make_example("new_variables", i).family for i in range(60)}
    assert train <= set(tdata.TRAIN_FAMILIES)
    assert newv <= set(tdata.NEW_VARIABLE_FAMILIES)
    assert not train & newv
    assert {tdata.make_example("theory", i).family for i in range(5)} == {"theory"}


def test_labels_match_planted_signals() -> None:
    lin = tdata.make_example("train", 1, min_snr=1.0, label=1)
    assert lin.slope != 0 and lin.step_target.max() == 0
    step = tdata.make_example("train", 2, label=2)
    assert step.slope == 0 and step.step_target.max() == 1.0
    none = tdata.make_example("train", 3, label=0)
    assert none.slope == 0 and none.snr == 0
    share = np.mean([tdata.make_example("train", i).label == 0 for i in range(400)])
    assert share == pytest.approx(tdata.NO_SIGNAL_SHARE, abs=0.08)


def test_featurize_is_scale_free() -> None:
    x = np.random.default_rng(0).normal(size=240)
    months = np.arange(240) % 12 + 1
    f1, _, _, s1 = tdata.featurize(x, months)
    f2, _, _, s2 = tdata.featurize(10 * x + 5, months)
    np.testing.assert_allclose(f1, f2, atol=1e-5)
    assert s2 == pytest.approx(10 * s1)


# ---------------------------------------------------------------- advisory integration


def _fake(cls: str, slope: float, conf: str = "high", agrees: bool = True) -> AiOpinion:
    probs = dict.fromkeys(tdata.CLASSES, 0.0)
    probs[cls] = 1.0
    return AiOpinion(
        model_version="test",
        class_probs=probs,
        predicted_class=cls,
        slope_per_decade=slope,
        slope_pi90=(slope - 0.1, slope + 0.1),
        confidence=conf,  # type: ignore[arg-type]
        agrees_with_statistics=agrees,
    )


def test_no_model_means_no_opinion(tmp_path: Path) -> None:
    assert rt.active_version(tmp_path) is None
    assert rt.ai_opinion(np.zeros(240), np.arange(240) % 12 + 1, True, 1, tmp_path) is None
    s, _ = synthetic_case(n_years=40, slope_per_decade=0.7, phi=0.5, seed=1)
    pr = build_protocol(s)
    assert pr.item("ai_expert") is None


@pytest.mark.parametrize(
    ("cls", "slope", "conf", "status", "disagree"),
    [
        ("linear", 0.7, "high", "pass", False),
        ("accelerating", 0.7, "medium", "pass", False),
        ("trend_plus_step", 0.7, "high", "partial", False),
        ("linear", 0.7, "low", "partial", False),
        ("step", 0.0, "high", "fail", True),
        ("no_trend", 0.0, "high", "fail", True),
        ("linear", -0.7, "high", "fail", True),
    ],
)
def test_ai_expert_is_advisory(
    monkeypatch: pytest.MonkeyPatch, cls: str, slope: float, conf: str, status: str, disagree: bool
) -> None:
    s, _ = synthetic_case(n_years=45, slope_per_decade=0.7, phi=0.5, seed=1)
    base = build_protocol(s)
    monkeypatch.setattr(rt, "ai_opinion", lambda *a, **k: _fake(cls, slope, conf))
    pr = build_protocol(s)
    item = pr.item("ai_expert")
    assert item is not None and item.advisory and item.status == status
    assert pr.verdict == base.verdict and pr.strength == base.strength  # never changes it
    assert ("ai_disagrees" in pr.caveats) == disagree
