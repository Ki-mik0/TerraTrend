"""Coverage for advisory AI item in the protocol (section 6.7) and the grid product."""

import numpy as np
import pytest

from earthtrend.analytics import analyze, analyze_grid, build_protocol
from earthtrend.analytics.models import AiOpinion
from earthtrend.analytics.simulate.synthetic import default_meta, generate_grid, synthetic_case


def _opinion(cls: str, slope: float = 0.7, conf: str = "high") -> AiOpinion:
    return AiOpinion(
        model_version="test",
        class_probs={cls: 1.0},
        predicted_class=cls,
        slope_per_decade=slope,
        slope_pi90=(slope - 0.1, slope + 0.1),
        confidence=conf,  # type: ignore[arg-type]
        agrees_with_statistics=True,
    )


def _series(slope: float):
    return synthetic_case(
        meta=default_meta(dataset_id="p"),
        n_years=45,
        base=260.0,
        seasonal_amplitude=15.0,
        slope_per_decade=slope,
        phi=0.5,
        seed=1,
    )[0]


@pytest.mark.parametrize(
    ("slope", "op", "status", "disagrees"),
    [
        (0.7, _opinion("linear"), "pass", False),
        (0.7, _opinion("accelerating"), "pass", False),
        (0.7, _opinion("step"), "fail", True),
        (0.7, _opinion("no_trend", 0.0), "fail", True),
        (0.7, _opinion("trend_plus_step"), "partial", False),
        (0.7, _opinion("linear", conf="low"), "partial", False),
        (0.7, _opinion("linear", slope=-0.7), "fail", True),
        (0.0, _opinion("no_trend", 0.0), "pass", False),
        (0.0, _opinion("linear"), "pass", True),
    ],
)
def test_ai_expert_item_status_is_advisory(
    monkeypatch: pytest.MonkeyPatch, slope: float, op: AiOpinion, status: str, disagrees: bool
) -> None:
    monkeypatch.setattr(analyze, "_ai_opinion", lambda *a, **k: op)
    pr = build_protocol(_series(slope))
    item = pr.item("ai_expert")
    assert item is not None and item.advisory
    if slope > 0:
        assert item.status == status
        assert ("ai_disagrees" in pr.caveats) == disagrees
    # advisory: the verdict is identical to a run without any AI item
    monkeypatch.setattr(analyze, "_ai_opinion", lambda *a, **k: None)
    plain = build_protocol(_series(slope))
    assert plain.item("ai_expert") is None
    assert (pr.verdict, pr.strength) == (plain.verdict, plain.strength)


def test_grid_rejects_mismatched_region_mask() -> None:
    lat, lon = np.arange(0.5, 6), np.arange(0.5, 6)
    dates, cube = generate_grid(slope_field=np.zeros((6, 6)), n_years=20, seed=1)
    with pytest.raises(ValueError, match="region_mask shape"):
        analyze_grid(cube, lat, lon, dates, region_mask=np.ones((3, 3)))


def test_grid_domain_mask_and_ai_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    from earthtrend.analytics.ml import trendnet

    lat, lon = np.arange(0.5, 8), np.arange(0.5, 8)
    dates, cube = generate_grid(slope_field=np.ones((8, 8)), n_years=20, phi=0.3, seed=2)
    land = np.ones((8, 8), bool)
    land[:, 4:] = False
    calls: dict[str, tuple[int, int]] = {}

    def fake(anom: np.ndarray, months: np.ndarray, *a: object, **k: object):
        calls["shape"] = anom.shape  # (valid cells, time)
        n = anom.shape[0]
        return np.full(n, 1, dtype=np.int64), np.full(n, 0.25)

    monkeypatch.setattr(trendnet, "classify_grid", fake)
    prod = analyze_grid(cube, lat, lon, dates, domain_mask=land, ai=True)
    assert prod.ai_class is not None and prod.ai_step_prob is not None
    assert prod.ai_class.shape == (8, 8)
    assert (prod.ai_class[:, 4:] == -1).all() and (prod.ai_class[:, :4] == 1).all()
    assert np.isnan(prod.ai_step_prob[:, 4:]).all()
    assert calls["shape"][0] == int(prod.fields.valid.sum())

    monkeypatch.setattr(trendnet, "classify_grid", lambda *a, **k: None)
    none_prod = analyze_grid(cube, lat, lon, dates, domain_mask=land, ai=True)
    assert none_prod.ai_class is None and none_prod.ai_step_prob is None
