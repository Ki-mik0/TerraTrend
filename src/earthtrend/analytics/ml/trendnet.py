"""Inference of M1 TrendNet inside the app (PLAN_ANALYTICS 11.2, 6.7). ONNX Runtime, CPU.

Model version: ``models/trendnet/<version>/`` with ``model.onnx`` (the 5-member ensemble with
temperature and interval scaling built in), ``meta.json`` (version, detection threshold),
``config.yaml``, ``data_manifest.json``, ``metrics.json``, ``gates.json``, ``model_card.md``.
``models/trendnet/ACTIVE`` names the version that passed its gates (written by ``promote``).

Without an active model, or without ``onnxruntime``, every function returns ``None``: the
app works on classical statistics alone (section 16). The opinion is advisory and never
enters the verdict.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from earthtrend.analytics.models import AiOpinion
from earthtrend.analytics.training.trendnet.data import CLASSES, MAX_LEN, featurize

MODEL_NAME = "trendnet"
ACTIVE_FILE = "ACTIVE"
CONFIDENCE_SPREAD = (0.05, 0.15)  # ensemble sd of the top-class probability: high / medium


def models_root(models_dir: str | Path | None = None) -> Path:
    if models_dir is not None:
        return Path(models_dir)
    env = os.environ.get("MODELS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "models"


def active_version(models_dir: str | Path | None = None) -> str | None:
    marker = models_root(models_dir) / MODEL_NAME / ACTIVE_FILE
    if not marker.exists():
        return None
    v = marker.read_text(encoding="utf-8").strip()
    return v or None


@dataclass(frozen=True)
class LoadedModel:
    version: str
    session: Any
    threshold: float  # P(no_trend) below this = the model sees a change


@lru_cache(maxsize=4)
def _load(path: str, version: str) -> LoadedModel | None:
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    vdir = Path(path) / MODEL_NAME / version
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    sess = ort.InferenceSession(str(vdir / "model.onnx"), providers=["CPUExecutionProvider"])
    return LoadedModel(version=version, session=sess, threshold=float(meta["threshold"]))


def load_active(models_dir: str | Path | None = None) -> LoadedModel | None:
    v = active_version(models_dir)
    if v is None:
        return None
    return _load(str(models_root(models_dir)), v)


def run(model: LoadedModel, features: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
    names = ["class_probs", "member_probs", "slope_mean", "slope_sd", "step_prob"]
    outs = model.session.run(
        names, {"features": features.astype(np.float32), "mask": mask.astype(np.float32)}
    )
    return dict(zip(names, outs, strict=True))


def _confidence(member_top: np.ndarray, top: float) -> str:
    spread = float(np.std(member_top))
    if top < 0.5 or spread > CONFIDENCE_SPREAD[1]:
        return "low"
    return "high" if spread <= CONFIDENCE_SPREAD[0] else "medium"


def ai_opinion(
    anomalies: np.ndarray,
    months: np.ndarray,
    stats_significant: bool,
    stats_sign: int,
    models_dir: str | Path | None = None,
) -> AiOpinion | None:
    """Opinion for one monthly anomaly series (gaps as NaN). None without an active model."""
    model = load_active(models_dir)
    if model is None or np.isfinite(anomalies).sum() < 24:
        return None
    feats, mask, _, scale = featurize(np.asarray(anomalies, float), np.asarray(months))
    out = run(model, feats[None], mask[None])
    p = out["class_probs"][0]
    top = int(np.argmax(p))
    slope = float(out["slope_mean"][0]) * scale
    sd = float(out["slope_sd"][0]) * scale
    n = int(mask.sum())
    sees_change = bool(p[0] < model.threshold)
    trend_classes = {"linear", "accelerating", "trend_plus_step"}
    ai_trend = sees_change and CLASSES[top] in trend_classes
    agrees = (ai_trend == stats_significant) and (
        not ai_trend or np.sign(slope) == stats_sign or stats_sign == 0
    )
    return AiOpinion(
        model_version=model.version,
        class_probs={c: float(v) for c, v in zip(CLASSES, p, strict=True)},
        predicted_class=CLASSES[top],
        slope_per_decade=slope,
        slope_pi90=(slope - 1.6448536 * sd, slope + 1.6448536 * sd),
        changepoint_probs=[float(v) for v in out["step_prob"][0, :n]],
        confidence=_confidence(out["member_probs"][:, 0, top], float(p[top])),
        agrees_with_statistics=bool(agrees),
    )


def classify_grid(
    anomalies: np.ndarray,
    months: np.ndarray,
    models_dir: str | Path | None = None,
    batch_size: int = 512,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Batch inference for map cells: ``anomalies`` (cells, time) -> (class index, max step
    probability) per cell; class -1 for cells with too little data. None without a model."""
    model = load_active(models_dir)
    if model is None:
        return None
    nc = anomalies.shape[0]
    cls = np.full(nc, -1, dtype=np.int64)
    step = np.full(nc, np.nan)
    for s in range(0, nc, batch_size):
        rows = range(s, min(s + batch_size, nc))
        feats = np.zeros((len(rows), 5, MAX_LEN), dtype=np.float32)
        masks = np.zeros((len(rows), MAX_LEN), dtype=np.float32)
        ok = np.zeros(len(rows), dtype=bool)
        for k, r in enumerate(rows):
            if np.isfinite(anomalies[r]).sum() >= 24:
                feats[k], masks[k], _, _ = featurize(anomalies[r], months)
                ok[k] = True
        if not ok.any():
            continue
        out = run(model, feats[ok], masks[ok])
        idx = np.array(list(rows))[ok]
        cls[idx] = out["class_probs"].argmax(1)
        step[idx] = out["step_prob"].max(1)
    return cls, step
