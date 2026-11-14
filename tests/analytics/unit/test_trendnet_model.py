"""M1 TrendNet model and ONNX runtime (skipped without torch / onnxruntime)."""

from pathlib import Path

import numpy as np
import pytest

from earthtrend.analytics.ml import trendnet as rt
from earthtrend.analytics.training.trendnet import data as tdata

torch = pytest.importorskip("torch")
onnxruntime = pytest.importorskip("onnxruntime")


@pytest.fixture(scope="module")
def tiny_version(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from earthtrend.analytics.training.trendnet import pipeline
    from earthtrend.analytics.training.trendnet.model import Ensemble, TrendNet

    root = tmp_path_factory.mktemp("models")
    vdir = root / "trendnet" / "0.0.1"
    vdir.mkdir(parents=True)
    torch.manual_seed(0)
    members = [TrendNet(channels=16, dilations=(1, 2, 4)) for _ in range(2)]
    ens = Ensemble(members, temperature=1.0, slope_sd_scale=1.0).eval()
    cfg = {"channels": 16, "dilations": [1, 2, 4], "dropout": 0.1, "n_members": 2}
    torch.save(
        {"config": cfg, "state": ens.state_dict(), "temperature": 1.0, "sd_scale": 1.0},
        vdir / "ensemble.pt",
    )
    pipeline.cmd_export("0.0.1", root)  # raises if ONNX differs from PyTorch by > 1e-4
    (vdir / "meta.json").write_text('{"version": "0.0.1", "threshold": 0.5}', encoding="utf-8")
    return root


def test_model_shapes_and_parameter_budget() -> None:
    from earthtrend.analytics.training.trendnet.model import TrendNet, n_parameters

    m = TrendNet().eval()
    assert 0.8e6 <= n_parameters(m) <= 3e6  # section 11.2: 1-3 M parameters
    b = tdata.batch("val", range(3))
    with torch.no_grad():
        logits, mu, logvar, step = m(torch.from_numpy(b["features"]), torch.from_numpy(b["mask"]))
    assert logits.shape == (3, 5) and mu.shape == (3,) and step.shape == (3, tdata.MAX_LEN)


def test_onnx_runtime_opinion_is_deterministic(tiny_version: Path) -> None:
    (tiny_version / "trendnet" / "ACTIVE").write_text("0.0.1", encoding="utf-8")
    rt._load.cache_clear()
    x = np.random.default_rng(1).normal(size=360)
    months = np.arange(360) % 12 + 1
    a = rt.ai_opinion(x, months, False, 0, tiny_version)
    b = rt.ai_opinion(x, months, False, 0, tiny_version)
    assert a is not None and a == b
    assert sum(a.class_probs.values()) == pytest.approx(1.0, abs=1e-5)
    assert a.slope_pi90[0] <= a.slope_per_decade <= a.slope_pi90[1]
    assert len(a.changepoint_probs or []) == 360
    grid = rt.classify_grid(np.stack([x, np.full(360, np.nan)]), months, tiny_version)
    assert grid is not None and grid[0][1] == -1 and 0 <= grid[0][0] < 5


def test_promote_refuses_failed_gates(tiny_version: Path) -> None:
    from earthtrend.analytics.training.trendnet import pipeline

    vdir = tiny_version / "trendnet" / "0.0.1"
    (vdir / "gates.json").write_text(
        '{"passed": false, "criteria": {"x": false}}', encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        pipeline.cmd_promote("0.0.1", tiny_version)
