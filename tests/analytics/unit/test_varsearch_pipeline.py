"""M3 VarSearch pipeline (stage A10): artifacts, gate wiring, promote. The fast test uses the
hashing encoder; the real fine-tune is `slow` and needs the optional `varsearch` group."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from earthtrend.analytics.ml.varsearch import VarSearch, active_version
from earthtrend.analytics.ml.varsearch_catalog import load_catalog
from earthtrend.analytics.training.varsearch.__main__ import main as cli
from earthtrend.analytics.training.varsearch.generate import GeneratorConfig
from earthtrend.analytics.training.varsearch.human_test import HUMAN_TEST_DIR, PLACEHOLDER_FILE
from earthtrend.analytics.training.varsearch.pipeline import promote, run
from earthtrend.analytics.training.varsearch.train import TrainConfig

SMALL = GeneratorConfig(per_variable_lang=6, phenomenon_variants=1)


def test_pipeline_writes_all_artifacts(tmp_path: Path) -> None:
    out = run(
        "t1",
        models_dir=tmp_path,
        encoder="hashing",
        generator_config=SMALL,
        human_test_dir=tmp_path / "no_human",
    )
    vdir = Path(out["version_dir"])
    for name in (
        "config.yaml",
        "data_manifest.json",
        "metrics.json",
        "gates.json",
        "model_card.md",
        "data/pairs_train.jsonl",
        "data/pairs_dev.jsonl",
    ):
        assert (vdir / name).is_file(), name
    gates = json.loads((vdir / "gates.json").read_text(encoding="utf-8"))
    assert gates["overall"] == "not_evaluated"
    manifest = json.loads((vdir / "data_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["outputs"]["pairs_train.jsonl"]) == 64
    assert manifest["inputs"]["human_test_sha256"] is None
    metrics = json.loads((vdir / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["synthetic_dev"]) == {
        "bm25",
        "base_dense",
        "base_hybrid",
        "tuned_dense",
        "tuned_hybrid",
    }
    assert metrics["human_test"] is None
    assert "not_evaluated" in (vdir / "model_card.md").read_text(encoding="utf-8")
    assert (tmp_path / "varsearch" / "experiments.jsonl").is_file()
    cfg = yaml.safe_load((vdir / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["encoder"]["kind"] == "hashing"

    with pytest.raises(PermissionError):
        promote("t1", tmp_path)
    assert active_version(tmp_path) is None
    with pytest.raises(FileExistsError):
        run("t1", models_dir=tmp_path, encoder="hashing", generator_config=SMALL)


def test_small_human_test_stays_not_evaluated(tmp_path: Path) -> None:
    human_dir = tmp_path / "human"
    human_dir.mkdir()
    shutil.copyfile(HUMAN_TEST_DIR / PLACEHOLDER_FILE, human_dir / "human_test.csv")
    out = run(
        "t2",
        models_dir=tmp_path,
        encoder="hashing",
        generator_config=SMALL,
        human_test_dir=human_dir,
    )
    assert out["gates"]["overall"] == "not_evaluated"
    assert "too small" in out["gates"]["reason"]


def test_promote_only_after_pass(tmp_path: Path) -> None:
    run(
        "t3",
        models_dir=tmp_path,
        encoder="hashing",
        generator_config=SMALL,
        human_test_dir=tmp_path / "none",
    )
    gates_path = tmp_path / "varsearch" / "t3" / "gates.json"
    gates_path.write_text(json.dumps({"overall": "pass"}), encoding="utf-8")
    assert cli(["--models-dir", str(tmp_path), "promote", "t3"]) == 0
    assert active_version(tmp_path) == "t3"
    s = VarSearch.from_models_dir(load_catalog(), tmp_path)
    assert s.mode == "hybrid" and s.model_version == "t3"


def test_cli_build_dataset(tmp_path: Path) -> None:
    assert cli(["build-dataset", str(tmp_path / "ds")]) == 0
    assert (tmp_path / "ds" / "data_manifest.json").is_file()


@pytest.mark.slow
@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="optional dependency group `varsearch` not installed",
)
def test_real_fine_tune_tiny(tmp_path: Path) -> None:
    """Downloads multilingual-e5-small; one short epoch on a small pair set."""
    out = run(
        "slow",
        models_dir=tmp_path,
        encoder="sentence-transformers",
        train_config=TrainConfig(epochs=1, batch_size=8),
        generator_config=GeneratorConfig(per_variable_lang=4, phenomenon_variants=1),
        human_test_dir=tmp_path / "none",
    )
    assert out["gates"]["overall"] == "not_evaluated"
    dev = out["metrics"]["synthetic_dev"]
    assert dev["tuned_hybrid"]["all"]["recall@5"] > 0.5
    s = VarSearch.from_models_dir(load_catalog(), tmp_path, version="slow", allow_ungated=True)
    assert s.mode == "hybrid"
