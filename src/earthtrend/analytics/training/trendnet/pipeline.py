"""``earthtrend ml`` steps for M1 TrendNet (PLAN_ANALYTICS 11.6).

    python -m earthtrend.analytics.training.trendnet train    --version 1.0.0 [--steps N]
    python -m earthtrend.analytics.training.trendnet evaluate --version 1.0.0
    python -m earthtrend.analytics.training.trendnet export   --version 1.0.0
    python -m earthtrend.analytics.training.trendnet promote  --version 1.0.0

``train`` also writes config.yaml and data_manifest.json; ``evaluate`` runs the exported
ONNX ensemble (what the app runs) and writes metrics.json and gates.json; ``promote``
writes ``models/trendnet/ACTIVE`` only if every gate passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from earthtrend.analytics.ml.trendnet import ACTIVE_FILE, MODEL_NAME, models_root
from earthtrend.analytics.training.trendnet import data as tdata

N_VAL_THRESHOLD = 8000
N_TEST = 6000


def _vdir(version: str, models_dir: Path | None) -> Path:
    return models_root(models_dir) / MODEL_NAME / version


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _code_hash() -> str:
    h = hashlib.sha256()
    for f in sorted(Path(tdata.__file__).parent.glob("*.py")):
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def cmd_train(
    version: str, steps: int | None, models_dir: Path | None, members: int | None
) -> None:
    from earthtrend.analytics.training.trendnet.train import TrainConfig, train_ensemble

    cfg = TrainConfig()
    if steps:
        cfg.steps = steps
    if members:
        cfg.n_members = members
    vdir = _vdir(version, models_dir)
    res = train_ensemble(cfg, vdir)
    (vdir / "config.yaml").write_text(
        yaml.safe_dump(asdict(cfg), sort_keys=False), encoding="utf-8"
    )
    manifest = {
        "model": MODEL_NAME,
        "version": version,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "generator_code_hash": _code_hash(),
        "data": "generated on the fly; deterministic in (split, index)",
        "seed_base": tdata.SEED_BASE,
        "train_families": tdata.TRAIN_FAMILIES,
        "held_out_families": tdata.NEW_VARIABLE_FAMILIES,
        "no_signal_share": tdata.NO_SIGNAL_SHARE,
        "years": [tdata.MIN_YEARS, tdata.MAX_YEARS],
        "real_data_templates": False,
        "temperature": res["temperature"],
        "slope_sd_scale": res["sd_scale"],
        "n_parameters_per_member": res["n_parameters_per_member"],
    }
    (vdir / "data_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: manifest[k] for k in ("temperature", "slope_sd_scale", "n_parameters_per_member")}
        )
    )


def cmd_export(version: str, models_dir: Path | None) -> None:
    import torch

    from earthtrend.analytics.training.trendnet.model import Ensemble, TrendNet
    from earthtrend.analytics.training.trendnet.train import TrainConfig

    vdir = _vdir(version, models_dir)
    ck = torch.load(vdir / "ensemble.pt", map_location="cpu", weights_only=False)
    cfg = TrainConfig(**{k: v for k, v in ck["config"].items() if k in TrainConfig.__annotations__})
    members = [
        TrendNet(cfg.channels, tuple(cfg.dilations), cfg.dropout) for _ in range(cfg.n_members)
    ]
    ens = Ensemble(members, ck["temperature"], ck["sd_scale"])
    ens.load_state_dict(ck["state"])
    ens.eval()
    b = tdata.batch("val", range(8))
    f, m = torch.from_numpy(b["features"]), torch.from_numpy(b["mask"])
    torch.onnx.export(
        ens,
        (f, m),
        str(vdir / "model.onnx"),
        input_names=["features", "mask"],
        output_names=["class_probs", "member_probs", "slope_mean", "slope_sd", "step_prob"],
        dynamic_axes={
            "features": {0: "batch"},
            "mask": {0: "batch"},
            "class_probs": {0: "batch"},
            "member_probs": {1: "batch"},
            "slope_mean": {0: "batch"},
            "slope_sd": {0: "batch"},
            "step_prob": {0: "batch"},
        },
        opset_version=17,
        dynamo=False,
    )
    import onnxruntime as ort

    sess = ort.InferenceSession(str(vdir / "model.onnx"), providers=["CPUExecutionProvider"])
    onnx_out = sess.run(None, {"features": b["features"], "mask": b["mask"]})
    with torch.no_grad():
        torch_out = [t.numpy() for t in ens(f, m)]
    diff = max(float(np.max(np.abs(a - c))) for a, c in zip(onnx_out, torch_out, strict=True))
    print(json.dumps({"onnx_vs_torch_max_abs_diff": diff}))
    if diff > 1e-4:
        raise SystemExit(f"ONNX output differs from PyTorch by {diff:.2e} (> 1e-4)")


def _onnx_predictor(vdir: Path):  # type: ignore[no-untyped-def]
    import onnxruntime as ort

    sess = ort.InferenceSession(str(vdir / "model.onnx"), providers=["CPUExecutionProvider"])
    names = ["class_probs", "member_probs", "slope_mean", "slope_sd", "step_prob"]

    def predict(features: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
        return dict(zip(names, sess.run(names, {"features": features, "mask": mask}), strict=True))

    return predict


def cmd_evaluate(version: str, models_dir: Path | None, n_test: int) -> dict[str, Any]:
    from earthtrend.analytics.training.trendnet.evaluate import (
        TEST_SPLITS,
        detection_threshold,
        evaluate_split,
        gates,
        predict_split,
    )

    vdir = _vdir(version, models_dir)
    predict = _onnx_predictor(vdir)
    # Threshold on a val range disjoint from the one used for temperature scaling.
    val = predict_split(predict, "val", N_VAL_THRESHOLD)
    tau = detection_threshold(val)
    metrics: dict[str, Any] = {"threshold": tau}
    for split in TEST_SPLITS:
        res = predict_split(predict, split, n_test)
        metrics[split] = evaluate_split(res, tau)
        print(
            split,
            json.dumps(
                {k: v for k, v in metrics[split].items() if k not in ("confusion", "power_by_snr")}
            ),
            flush=True,
        )
    g = gates(metrics)
    (vdir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (vdir / "gates.json").write_text(json.dumps(g, indent=2), encoding="utf-8")
    (vdir / "meta.json").write_text(
        json.dumps({"version": version, "threshold": tau, "classes": tdata.CLASSES}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"passed": g["passed"]}))
    return g


def cmd_promote(version: str, models_dir: Path | None) -> None:
    vdir = _vdir(version, models_dir)
    g = json.loads((vdir / "gates.json").read_text(encoding="utf-8"))
    if not g.get("passed"):
        failed = [k for k, ok in g["criteria"].items() if not ok]
        raise SystemExit(f"gates not passed, {MODEL_NAME} {version} stays hidden: {failed}")
    (vdir.parent / ACTIVE_FILE).write_text(version, encoding="utf-8")
    print(f"{MODEL_NAME} {version} is active")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="earthtrend ml trendnet")
    ap.add_argument("command", choices=["train", "export", "evaluate", "promote"])
    ap.add_argument("--version", required=True)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--members", type=int)
    ap.add_argument("--n-test", type=int, default=N_TEST)
    ap.add_argument("--models-dir", type=Path)
    a = ap.parse_args(argv)
    if a.command == "train":
        cmd_train(a.version, a.steps, a.models_dir, a.members)
    elif a.command == "export":
        cmd_export(a.version, a.models_dir)
    elif a.command == "evaluate":
        cmd_evaluate(a.version, a.models_dir, a.n_test)
    else:
        cmd_promote(a.version, a.models_dir)


if __name__ == "__main__":
    main()
