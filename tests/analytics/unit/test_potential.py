"""M2 TrendPotential, the "Informant" (PLAN_ANALYTICS section 11.3, stage A9)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from earthtrend.analytics.ml.features import (
    FEATURE_NAMES,
    Vocab,
    assert_no_leak,
    build_matrix,
    reason_for,
)
from earthtrend.analytics.ml.potential import active_model, clear_cache, predict_potential
from earthtrend.analytics.ml.potential_models import RegionFeatures, VariableInfo
from earthtrend.analytics.training.potential.data import (
    build_dataset,
    labels_from_candidates,
    random_region_masks,
    region_features_from_rasters,
    spatial_block,
    synthetic_world,
)
from earthtrend.analytics.training.potential.evaluate import ece, recall_at_k

# ---------------------------------------------------------------- features and data


def test_no_target_leak_in_features() -> None:
    assert_no_leak(FEATURE_NAMES)
    with pytest.raises(ValueError, match="leak"):
        assert_no_leak([*FEATURE_NAMES, "slope_per_decade"])


def test_unknown_variable_gets_nan_code() -> None:
    vocab = Vocab.fit([VariableInfo(variable_id="a", concept_id="c", domain="land")])
    reg = RegionFeatures(region_id="r", lat=10, lon=20, area_km2=1000)
    x = build_matrix(
        [(reg, VariableInfo(variable_id="zzz", concept_id="c", domain="land"), "JJA")], vocab
    )
    j = FEATURE_NAMES.index("variable_code")
    assert np.isnan(x[0, j])
    assert x[0, FEATURE_NAMES.index("concept_code")] == 0.0
    assert x[0, FEATURE_NAMES.index("season_code")] == 3.0


def test_labels_from_radar_candidates() -> None:
    cands = [
        SimpleNamespace(
            region_id="r",
            variable_id="v",
            season="annual",
            slope_per_decade=0.3,
            q_variable=0.01,
            snr=-0.7,
            skipped=None,
        ),
        SimpleNamespace(
            region_id="r",
            variable_id="w",
            season="JJA",
            slope_per_decade=-0.1,
            q_variable=0.4,
            snr=0.1,
            skipped=None,
        ),
        SimpleNamespace(
            region_id="r",
            variable_id="x",
            season="annual",
            slope_per_decade=None,
            q_variable=None,
            snr=None,
            skipped="short_record",
        ),
    ]
    labels = labels_from_candidates(cands)
    assert [(lb.variable_id, lb.significant, lb.sign, lb.snr) for lb in labels] == [
        ("v", True, 1, 0.7),
        ("w", False, -1, 0.1),
    ]


def test_spatial_blocks() -> None:
    assert spatial_block(0, 0) == spatial_block(29, 59)
    assert spatial_block(0, 0) != spatial_block(31, 0)
    assert spatial_block(10, 190) == spatial_block(10, -170)
    assert spatial_block(90, 180) == "b5_0"  # lon 180 wraps to -180


def test_random_regions_and_raster_features() -> None:
    lat = np.arange(-89.0, 90.0, 2.0)
    lon = np.arange(-179.0, 180.0, 2.0)
    masks = random_region_masks(lat, lon, 20, seed=1)
    assert len(masks) == 20
    assert all(m.sum() >= 4 for _, m in masks)
    assert {n.split("_")[1] for n, _ in masks} == {"rect", "circ"}

    glat = np.meshgrid(lat, lon, indexing="ij")[0]
    rasters = {
        "clim_t_c": 30 - 0.5 * np.abs(glat),
        "lc_forest": np.full(glat.shape, 0.25),
        "elevation_m": np.where(glat > 0, 1000.0, 0.0),
        "koppen_code": np.full(glat.shape, 2.0),
    }
    m = (np.abs(glat - 50) < 5) & (np.abs(np.meshgrid(lat, lon, indexing="ij")[1] - 10) < 5)
    rf = region_features_from_rasters("box", m, lat, lon, rasters)
    assert rf.lat == pytest.approx(50, abs=0.5)
    assert rf.lon == pytest.approx(10, abs=0.5)
    assert rf.clim_t_c == pytest.approx(5, abs=0.5)
    assert rf.land_cover == {"forest": 0.25}
    assert rf.elev_mean_m == 1000.0 and rf.elev_range_m == 0.0
    assert rf.koppen == "C"
    assert rf.area_km2 > 0


def test_build_dataset_drops_unknown_regions() -> None:
    labels, regions, variables = synthetic_world(10, seed=0)
    regions.pop("syn_0")
    ds = build_dataset(labels, regions, variables)
    assert ds.meta["n_dropped"] == 16  # 8 variables x 2 seasons
    assert ds.x.shape == (len(labels) - 16, len(FEATURE_NAMES))
    assert len(ds.content_hash()) == 16


def test_reason_codes() -> None:
    assert reason_for("abs_lat", 70) == "high_latitude"
    assert reason_for("abs_lat", 10) == "tropical"
    assert reason_for("abs_lat", 40) is None
    assert reason_for("aridity_index", 0.1) == "arid_climate"
    assert reason_for("pop_change_pct", 30) == "rapid_urban_growth"
    assert reason_for("variable_code", 3) == "variable_prior"
    assert reason_for("clim_t_c", -5) == "cold_climate"
    assert reason_for("clim_t_c", float("nan")) is None


def test_metric_helpers() -> None:
    y = np.array([True, False, True, False])
    assert ece(np.array([1.0, 0.0, 1.0, 0.0]), y) == 0.0
    assert ece(np.full(4, 0.5), y) == 0.0
    score = np.array([0.9, 0.8, 0.1, 0.2])
    # one group: 2 significant, top-5 holds all 4 -> recall 1; top-1 holds 1 of min(1, 2)
    assert recall_at_k(score, y, ["r"] * 4, ["annual"] * 4) == 1.0
    assert recall_at_k(score, y, ["r"] * 4, ["annual"] * 4, k=1) == 1.0
    worst = np.array([0.1, 0.9, 0.2, 0.8])  # top-1 is a non-significant variable
    assert recall_at_k(worst, y, ["r"] * 4, ["annual"] * 4, k=1) == 0.0


# ---------------------------------------------------------------- inference without a model


def test_no_active_model_returns_empty_page(tmp_path: Path) -> None:
    clear_cache()
    reg = RegionFeatures(region_id="r", lat=0, lon=0, area_km2=10)
    page = predict_potential(reg, [], root=tmp_path)
    assert page.items == [] and page.fallback_reason == "no_active_model"
    (tmp_path / "potential" / "v1").mkdir(parents=True)
    (tmp_path / "potential" / "ACTIVE").write_text("v1")
    (tmp_path / "potential" / "v1" / "gates.json").write_text(json.dumps({"status": "fail"}))
    assert active_model(tmp_path) == (None, "gate_not_passed")


def test_core_import_does_not_load_lightgbm() -> None:
    code = (
        "import sys, earthtrend.analytics.ml.potential, earthtrend.analytics.ml.features;"
        "print('lightgbm' in sys.modules, 'sklearn' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONPATH": "src"},
    )
    assert out.stdout.strip() == "False False"


# ---------------------------------------------------------------- training


@pytest.fixture(scope="module")
def small_model(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict, dict]:
    pytest.importorskip("lightgbm")
    pytest.importorskip("sklearn")
    from earthtrend.analytics.training.potential.model import TrainConfig
    from earthtrend.analytics.training.potential.pipeline import train_version

    labels, regions, variables = synthetic_world(120, seed=2)
    ds = build_dataset(labels, regions, variables)
    root = tmp_path_factory.mktemp("models")
    cfg = TrainConfig(n_estimators=40, calibration_folds=3)
    g = train_version(ds, "t1", cfg, root, source="radar", n_folds=3)
    train_version(ds, "syn", cfg, root, source="synthetic", n_folds=3)
    return root, regions, {"gates": g, "variables": variables}


def test_artifacts_written(small_model: tuple[Path, dict, dict]) -> None:
    root, _, info = small_model
    vdir = root / "potential" / "t1"
    for name in (
        "significance.txt",
        "sign.txt",
        "snr_q10.txt",
        "snr_q90.txt",
        "calibration.json",
        "config.yaml",
        "data_manifest.json",
        "metrics.json",
        "gates.json",
        "model_card.md",
    ):
        assert (vdir / name).is_file(), name
    manifest = json.loads((vdir / "data_manifest.json").read_text())
    assert manifest["n_variables"] == 8
    metrics = json.loads((vdir / "metrics.json").read_text())
    assert set(metrics["spatial_blocks"]) == {"m2", "frequency", "knn"}
    assert "cold_start_variables" in metrics
    assert info["gates"]["status"] in {"pass", "fail"}
    lines = (root / "potential" / "experiments.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_synthetic_source_can_never_be_promoted(small_model: tuple[Path, dict, dict]) -> None:
    from earthtrend.analytics.training.potential.pipeline import promote

    root, _, _ = small_model
    with pytest.raises(PermissionError):
        promote("syn", root)


def test_version_is_never_overwritten(small_model: tuple[Path, dict, dict]) -> None:
    from earthtrend.analytics.training.potential.pipeline import train_version

    root, regions, info = small_model
    labels, regions2, variables = synthetic_world(60, seed=3)
    with pytest.raises(FileExistsError):
        train_version(build_dataset(labels, regions2, variables), "t1", root=root)


def test_predict_after_promote(small_model: tuple[Path, dict, dict]) -> None:
    root, regions, info = small_model
    gates_path = root / "potential" / "t1" / "gates.json"
    g = json.loads(gates_path.read_text())
    g["status"] = "pass"  # force for the inference test; the real gate is tested (slow)
    gates_path.write_text(json.dumps(g))
    from earthtrend.analytics.training.potential.pipeline import promote

    promote("t1", root)
    reg = regions["syn_5"]
    page = predict_potential(
        reg, list(info["variables"].values()), ["annual", "JJA"], root=root, top_k=5
    )
    assert page.fallback_reason is None and page.model_version == "t1"
    assert len(page.items) == 5
    ps = [i.p_significant for i in page.items]
    assert ps == sorted(ps, reverse=True)
    for it in page.items:
        assert 0 <= it.p_significant <= 1
        assert it.expected_sign in (-1, 0, 1)
        assert 0 <= it.expected_snr[0] <= it.expected_snr[1]
        assert len(it.top_reasons) <= 3
        priors = [
            i for i, c in enumerate(it.top_reasons) if c in ("variable_prior", "season_prior")
        ]
        regional = [i for i, c in enumerate(it.top_reasons) if i not in priors]
        assert not priors or not regional or max(regional) < min(priors)
    # Reload from disk gives identical predictions (reproducible artifacts).
    clear_cache()
    again = predict_potential(
        reg, list(info["variables"].values()), ["annual", "JJA"], root=root, top_k=5
    )
    assert [i.p_significant for i in again.items] == ps


@pytest.mark.slow
def test_gates_pass_on_synthetic_world(tmp_path: Path) -> None:
    """M2 must learn the planted geographic rules better than both baselines (~1 min)."""
    pytest.importorskip("lightgbm")
    from earthtrend.analytics.training.potential.evaluate import evaluate, gates
    from earthtrend.analytics.training.potential.model import TrainConfig

    labels, regions, variables = synthetic_world(400, seed=0)
    g = gates(evaluate(build_dataset(labels, regions, variables), TrainConfig()))
    assert g["status"] == "pass", g


def test_labels_from_real_radar_candidate() -> None:
    from earthtrend.analytics.radar.models import RadarCandidate, radar_key

    c = RadarCandidate(
        key=radar_key("t2m", "arctic", "annual"),
        variable_id="t2m",
        concept_id="air_temperature",
        dataset_id="merra2",
        region_id="arctic",
        season="annual",
        n_years=45,
        slope_per_decade=0.7,
        q_variable=0.001,
        snr=1.2,
    )
    (lb,) = labels_from_candidates([c])
    assert (lb.region_id, lb.variable_id, lb.significant, lb.sign, lb.snr) == (
        "arctic",
        "t2m",
        True,
        1,
        1.2,
    )
