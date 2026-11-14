"""Validation and quality gates of M2 (section 11.3).

* **Spatial block CV**: whole 30 x 60 deg blocks are held out; random splits overrate
  the model because neighbouring regions are alike.
* **Cold start**: variables held out one group at a time; their ``variable_code`` is
  hidden (NaN) so the model must rely on concept, domain and descriptors.
* **Metrics**: ROC-AUC, PR-AUC, Brier, ECE, recall in the top 5 per (region, season).
* **Baselines**: (1) global frequency of significance of the variable (and season);
  (2) geographic kNN over the training regions with the same variable and season.
* **Gate**: on held-out blocks, recall@5 and Brier beat both baselines and ECE < 0.05.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics import config
from earthtrend.analytics.ml.features import FEATURE_NAMES
from earthtrend.analytics.training.potential.data import PotentialDataset
from earthtrend.analytics.training.potential.model import TrainConfig, _group_folds, train_model

ECE_MAX = 0.05
TOP_K = 5
KNN_K = 5
VAR_COL = FEATURE_NAMES.index("variable_code")


# ---------------------------------------------------------------- metrics


def ece(p: NDArray[np.float64], y: NDArray[np.bool_], bins: int = 10) -> float:
    """Expected calibration error with equal-width bins."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(float(p[m].mean()) - float(y[m].mean()))
    return total


def recall_at_k(
    score: NDArray[np.float64],
    y: NDArray[np.bool_],
    region_ids: list[str],
    seasons: list[str],
    k: int = TOP_K,
) -> float:
    """Mean over (region, season) groups with >= 1 significant variable of
    |significant in top k| / min(k, |significant|)."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, key in enumerate(zip(region_ids, seasons, strict=True)):
        groups[key].append(i)
    vals: list[float] = []
    for idx in groups.values():
        ia = np.array(idx)
        n_sig = int(y[ia].sum())
        if n_sig == 0:
            continue
        top = ia[np.argsort(-score[ia], kind="stable")[:k]]
        vals.append(float(y[top].sum()) / min(k, n_sig))
    return float(np.mean(vals)) if vals else math.nan


def metrics(
    score: NDArray[np.float64], y: NDArray[np.bool_], region_ids: list[str], seasons: list[str]
) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    both = 0 < y.sum() < y.size
    return {
        "roc_auc": float(roc_auc_score(y, score)) if both else math.nan,
        "pr_auc": float(average_precision_score(y, score)) if both else math.nan,
        "brier": float(np.mean((score - y) ** 2)),
        "ece": ece(score, y),
        "recall_at_5": recall_at_k(score, y, region_ids, seasons),
        "n": float(y.size),
        "base_rate": float(y.mean()) if y.size else math.nan,
    }


# ---------------------------------------------------------------- baselines


def baseline_frequency(train: PotentialDataset, test: PotentialDataset) -> NDArray[np.float64]:
    stats: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    var_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for v, s, y in zip(train.variable_ids, train.seasons, train.significant, strict=True):
        stats[(v, s)][0] += float(y)
        stats[(v, s)][1] += 1
        var_stats[v][0] += float(y)
        var_stats[v][1] += 1
    overall = float(train.significant.mean())
    out = np.empty(len(test))
    for i, (v, s) in enumerate(zip(test.variable_ids, test.seasons, strict=True)):
        a, n = stats.get((v, s), (0.0, 0.0))
        if n == 0:
            a, n = var_stats.get(v, (0.0, 0.0))
        out[i] = (a + overall) / (n + 1)  # one pseudo-count of the overall rate
    return out


def baseline_knn(
    train: PotentialDataset, test: PotentialDataset, k: int = KNN_K
) -> NDArray[np.float64]:
    by_key: dict[tuple[str, str], NDArray[np.int64]] = {}
    keys = list(zip(train.variable_ids, train.seasons, strict=True))
    tmp: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, key in enumerate(keys):
        tmp[key].append(i)
    for key, members in tmp.items():
        by_key[key] = np.array(members, dtype=np.int64)
    freq = baseline_frequency(train, test)
    out = np.empty(len(test))
    tl, tn = np.radians(train.lat), np.radians(train.lon)
    for i, key in enumerate(zip(test.variable_ids, test.seasons, strict=True)):
        idx = by_key.get(key)
        if idx is None or idx.size == 0:
            out[i] = freq[i]
            continue
        p1, l1 = math.radians(test.lat[i]), math.radians(test.lon[i])
        cosd = np.sin(tl[idx]) * math.sin(p1) + np.cos(tl[idx]) * math.cos(p1) * np.cos(
            tn[idx] - l1
        )
        near = idx[np.argsort(-cosd)[:k]]
        out[i] = float(train.significant[near].mean())
    return out


# ---------------------------------------------------------------- CV


def _cv(
    ds: PotentialDataset,
    folds: list[NDArray[np.int64]],
    cfg: TrainConfig,
    hide_variable: bool,
) -> dict[str, NDArray[np.float64]]:
    pred = {name: np.full(len(ds), np.nan) for name in ("m2", "frequency", "knn")}
    for f, test in enumerate(folds):
        train = np.setdiff1d(np.arange(len(ds)), test)
        tr, te = ds.subset(train), ds.subset(test)
        model = train_model(tr, cfg, version=f"cv{f}")
        x = te.x.copy()
        if hide_variable:
            x[:, VAR_COL] = np.nan
        pred["m2"][test] = model.predict_matrix(x)["p_significant"]
        pred["frequency"][test] = baseline_frequency(tr, te)
        pred["knn"][test] = baseline_knn(tr, te)
    return pred


def _score_all(ds: PotentialDataset, pred: dict[str, NDArray[np.float64]]) -> dict[str, Any]:
    ok = np.all([np.isfinite(v) for v in pred.values()], axis=0)
    rid = [r for r, m in zip(ds.region_ids, ok, strict=True) if m]
    sea = [s for s, m in zip(ds.seasons, ok, strict=True) if m]
    return {name: metrics(v[ok], ds.significant[ok], rid, sea) for name, v in pred.items()}


def evaluate(ds: PotentialDataset, cfg: TrainConfig, n_folds: int = 5) -> dict[str, Any]:
    spatial = _score_all(ds, _cv(ds, _group_folds(ds.blocks, n_folds), cfg, hide_variable=False))
    var_folds = _group_folds(ds.variable_ids, min(4, len(set(ds.variable_ids))))
    cold = _score_all(ds, _cv(ds, var_folds, cfg, hide_variable=True))
    return {"spatial_blocks": spatial, "cold_start_variables": cold, "n_rows": len(ds)}


def gates(result: dict[str, Any]) -> dict[str, Any]:
    sp = result["spatial_blocks"]
    m2, fq, kn = sp["m2"], sp["frequency"], sp["knn"]
    criteria = {
        "recall_at_5_beats_frequency": m2["recall_at_5"] > fq["recall_at_5"],
        "recall_at_5_beats_knn": m2["recall_at_5"] > kn["recall_at_5"],
        "brier_beats_frequency": m2["brier"] < fq["brier"],
        "brier_beats_knn": m2["brier"] < kn["brier"],
        "ece_below_0.05": m2["ece"] < ECE_MAX,
    }
    status = "pass" if all(criteria.values()) else "fail"
    return {
        "model": "potential",
        "status": status,
        "criteria": {k: bool(v) for k, v in criteria.items()},
        "values": {
            "recall_at_5": {
                "m2": m2["recall_at_5"],
                "frequency": fq["recall_at_5"],
                "knn": kn["recall_at_5"],
            },
            "brier": {"m2": m2["brier"], "frequency": fq["brier"], "knn": kn["brier"]},
            "ece": m2["ece"],
        },
        "analytics_version": config.ANALYTICS_VERSION,
    }
