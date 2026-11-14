"""Evaluation and quality gates of M1 TrendNet (PLAN_ANALYTICS 11.2).

Works on ensemble outputs (from PyTorch or ONNX) for the test splits and computes:
false alarms at the nominal 5% level, power vs MK-AR1, step/linear balanced accuracy vs
"BEAST + rules", 90% slope-interval coverage, ECE, degradation on unseen variables.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from earthtrend.analytics.training.trendnet.data import CLASSES, MAX_LEN, Split, batch
from earthtrend.analytics.trend.changepoint import detect_changepoints
from earthtrend.analytics.trend.mann_kendall import mk_ar1

Predictor = Callable[[np.ndarray, np.ndarray], dict[str, np.ndarray]]
TEST_SPLITS: tuple[Split, ...] = ("new_places", "new_variables", "theory")
STEP_JUMP_Z = 0.5  # baseline rule: a BEAST change point with |jump| >= 0.5 robust-z = "step"

GATES = {
    "false_alarm_range": (0.03, 0.07),
    "power_margin_vs_mk": 0.02,
    "step_linear_gain_vs_beast": 0.05,
    "coverage90_range": (0.87, 0.93),
    "ece_max": 0.03,
    "new_variables_degradation_max": 0.03,
}


def predict_split(predict: Predictor, split: Split, n: int, bs: int = 256) -> dict[str, np.ndarray]:
    parts: dict[str, list[np.ndarray]] = {}
    for start in range(0, n, bs):
        b = batch(split, range(start, min(start + bs, n)))
        out = predict(b["features"], b["mask"])
        for k, v in {**b, **out}.items():
            if k == "member_probs":
                parts.setdefault(k, []).append(np.moveaxis(v, 0, 1))
            else:
                parts.setdefault(k, []).append(v)
    res = {k: np.concatenate(v) for k, v in parts.items()}
    return res


def _series(features: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Recover the (robust-z) series with NaN gaps from the model input."""
    n = int(mask.sum())
    z = features[0, :n].astype(np.float64)
    z[features[1, :n] > 0.5] = np.nan
    return z


def detection_threshold(val: dict[str, np.ndarray], fa: float = 0.05) -> float:
    """P(no_trend) below this = "AI sees a change"; set so 5% of no-signal val series fire."""
    p_none = val["class_probs"][val["label"] == 0, 0]
    return float(np.quantile(p_none, fa))


def ece(probs: np.ndarray, labels: np.ndarray, bins: int = 15) -> float:
    conf = probs.max(1)
    pred = probs.argmax(1)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (conf > lo) & (conf <= hi)
        if sel.any():
            total += sel.mean() * abs(
                float((pred[sel] == labels[sel]).mean()) - float(conf[sel].mean())
            )
    return float(total)


def _balanced(pred_step: np.ndarray, is_step: np.ndarray) -> float:
    tpr = float(pred_step[is_step].mean()) if is_step.any() else 0.0
    tnr = float((~pred_step[~is_step]).mean()) if (~is_step).any() else 0.0
    return 0.5 * (tpr + tnr)


def evaluate_split(
    res: dict[str, np.ndarray], tau: float, n_baseline: int = 600, alpha: float = 0.05
) -> dict[str, Any]:
    labels = res["label"]
    probs = res["class_probs"]
    detect = probs[:, 0] < tau
    null = labels == 0
    linear = labels == 1
    out: dict[str, Any] = {"n": int(labels.size)}
    out["false_alarm"] = float(detect[null].mean())
    out["accuracy"] = float((probs.argmax(1) == labels).mean())
    out["ece"] = ece(probs, labels)
    lo = res["slope_mean"] - 1.6448536 * res["slope_sd"]
    hi = res["slope_mean"] + 1.6448536 * res["slope_sd"]
    out["coverage90"] = float(((res["slope"] >= lo) & (res["slope"] <= hi)).mean())

    # Power on linear trends vs MK-AR1 (same series), and MK's own false alarms.
    mk_detect = np.zeros(labels.size, dtype=bool)
    for i in np.flatnonzero(null | linear):
        mk = mk_ar1(_series(res["features"][i], res["mask"][i]))
        mk_detect[i] = bool(mk and mk.p_value < alpha)
    out["power_linear"] = float(detect[linear].mean())
    out["power_linear_mk"] = float(mk_detect[linear].mean())
    out["false_alarm_mk"] = float(mk_detect[null].mean())
    bins = [(0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 10.0)]
    out["power_by_snr"] = [
        {
            "snr": f"{a}-{b}",
            "ai": float(detect[linear & (res["snr"] >= a) & (res["snr"] < b)].mean())
            if (linear & (res["snr"] >= a) & (res["snr"] < b)).any()
            else None,
            "mk": float(mk_detect[linear & (res["snr"] >= a) & (res["snr"] < b)].mean())
            if (linear & (res["snr"] >= a) & (res["snr"] < b)).any()
            else None,
        }
        for a, b in bins
    ]

    # Step vs linear: model (step-like classes) vs BEAST + rules.
    sl = np.flatnonzero(np.isin(labels, [1, 2]))[:n_baseline]
    is_step = labels[sl] == 2
    ai_step = np.isin(probs[sl].argmax(1), [2, 4])
    base_step = np.zeros(sl.size, dtype=bool)
    for k, i in enumerate(sl):
        n = int(res["mask"][i].sum())
        z = _series(res["features"][i], res["mask"][i])
        t = 2000 + np.arange(n) / 12.0
        cps = detect_changepoints(t, z, step=1 / 12, seed=7)
        base_step[k] = any(c.jump is not None and abs(c.jump) >= STEP_JUMP_Z for c in cps)
    out["step_linear_bal_acc"] = _balanced(ai_step, is_step)
    out["step_linear_bal_acc_beast"] = _balanced(base_step, is_step)
    conf = np.zeros((len(CLASSES), len(CLASSES)), dtype=int)
    for a, b in zip(labels, probs.argmax(1), strict=True):
        conf[a, b] += 1
    out["confusion"] = conf.tolist()
    return out


def gates(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    g: dict[str, bool] = {}
    lo, hi = GATES["false_alarm_range"]
    for s in TEST_SPLITS:
        m = metrics[s]
        g[f"{s}: false alarms 3-7%"] = lo <= m["false_alarm"] <= hi
        g[f"{s}: power >= MK-AR1 - 2 pp"] = (
            m["power_linear"] >= m["power_linear_mk"] - GATES["power_margin_vs_mk"]
        )
        g[f"{s}: step/linear >= BEAST + 5 pp"] = (
            m["step_linear_bal_acc"]
            >= m["step_linear_bal_acc_beast"] + GATES["step_linear_gain_vs_beast"]
        )
        clo, chi = GATES["coverage90_range"]
        g[f"{s}: 90% interval coverage 87-93%"] = clo <= m["coverage90"] <= chi
        g[f"{s}: ECE < 0.03"] = m["ece"] < GATES["ece_max"]
    deg = GATES["new_variables_degradation_max"]
    np_, nv = metrics["new_places"], metrics["new_variables"]
    g["new variables: accuracy drop <= 3 pp"] = np_["accuracy"] - nv["accuracy"] <= deg
    g["new variables: step/linear drop <= 3 pp"] = (
        np_["step_linear_bal_acc"] - nv["step_linear_bal_acc"] <= deg
    )
    g["new variables: coverage drop <= 3 pp"] = abs(np_["coverage90"] - nv["coverage90"]) <= deg
    return {"criteria": g, "passed": all(g.values()), "thresholds": GATES}


__all__ = [
    "MAX_LEN",
    "TEST_SPLITS",
    "detection_threshold",
    "evaluate_split",
    "gates",
    "predict_split",
]
