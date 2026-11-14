"""Fit M2 (section 11.3): LightGBM significance classifier with isotonic calibration on
out-of-fold scores (spatial groups), sign classifier on significant rows, quantile
regression of |SNR| (10th and 90th percentile)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics.ml.features import CATEGORICAL, FEATURE_NAMES
from earthtrend.analytics.ml.potential import PotentialModel
from earthtrend.analytics.training.potential.data import PotentialDataset

CAT_IDX = [FEATURE_NAMES.index(c) for c in CATEGORICAL]


@dataclass(frozen=True)
class TrainConfig:
    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 15
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.9
    lambda_l2: float = 1.0
    calibration_folds: int = 5
    seed: int = 42

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _params(cfg: TrainConfig, objective: str, **extra: Any) -> dict[str, Any]:
    return {
        "objective": objective,
        "learning_rate": cfg.learning_rate,
        "num_leaves": cfg.num_leaves,
        "min_data_in_leaf": cfg.min_data_in_leaf,
        "feature_fraction": cfg.feature_fraction,
        "bagging_fraction": cfg.bagging_fraction,
        "bagging_freq": 1,
        "lambda_l2": cfg.lambda_l2,
        "seed": cfg.seed,
        "deterministic": True,
        "num_threads": 1,  # bit-for-bit reproducible (section 16)
        "verbosity": -1,
        **extra,
    }


def _fit(
    x: NDArray[np.float64], y: NDArray[np.float64], params: dict[str, Any], rounds: int
) -> Any:
    import lightgbm as lgb

    ds = lgb.Dataset(
        x,
        label=y,
        feature_name=list(FEATURE_NAMES),
        categorical_feature=CAT_IDX,
        free_raw_data=False,
    )
    return lgb.train(params, ds, num_boost_round=rounds)


def _group_folds(groups: list[str], k: int) -> list[NDArray[np.int64]]:
    """Test-index arrays of ``k`` folds that keep each group whole (spatial blocks)."""
    uniq = sorted(set(groups))
    k = max(2, min(k, len(uniq)))
    # balance folds by size: largest groups first, each into the currently smallest fold
    sizes = {g: 0 for g in uniq}
    for g in groups:
        sizes[g] += 1
    folds: list[list[str]] = [[] for _ in range(k)]
    load = [0] * k
    for g in sorted(uniq, key=lambda g: -sizes[g]):
        j = int(np.argmin(load))
        folds[j].append(g)
        load[j] += sizes[g]
    garr = np.array(groups)
    return [np.flatnonzero(np.isin(garr, f)) for f in folds if f]


def fit_isotonic(
    raw: NDArray[np.float64], y: NDArray[np.bool_]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(raw, y.astype(np.float64))
    return (
        np.asarray(iso.X_thresholds_, dtype=np.float64),
        np.asarray(iso.y_thresholds_, dtype=np.float64),
    )


def train_model(ds: PotentialDataset, cfg: TrainConfig, version: str) -> PotentialModel:
    if len(ds) < 50 or ds.significant.all() or not ds.significant.any():
        raise ValueError("need >= 50 labels with both significant and non-significant cases")
    y_sig = ds.significant.astype(np.float64)
    p_bin = _params(cfg, "binary")

    # Out-of-fold raw scores for calibration, folds = spatial blocks.
    oof = np.full(len(ds), np.nan)
    for test in _group_folds(ds.blocks, cfg.calibration_folds):
        train = np.setdiff1d(np.arange(len(ds)), test)
        if y_sig[train].min() == y_sig[train].max():
            continue
        b = _fit(ds.x[train], y_sig[train], p_bin, cfg.n_estimators)
        oof[test] = b.predict(ds.x[test])
    ok = np.isfinite(oof)
    iso_x, iso_y = fit_isotonic(oof[ok], ds.significant[ok])

    significance = _fit(ds.x, y_sig, p_bin, cfg.n_estimators)
    sig_rows = np.flatnonzero(ds.significant & (ds.sign != 0))
    if sig_rows.size < 10 or len(set(ds.sign[sig_rows].tolist())) < 2:
        raise ValueError("need significant cases of both signs to fit the sign model")
    sign = _fit(ds.x[sig_rows], (ds.sign[sig_rows] > 0).astype(np.float64), p_bin, cfg.n_estimators)
    q10 = _fit(ds.x, ds.snr, _params(cfg, "quantile", alpha=0.1), cfg.n_estimators)
    q90 = _fit(ds.x, ds.snr, _params(cfg, "quantile", alpha=0.9), cfg.n_estimators)
    return PotentialModel(
        version=version,
        significance=significance,
        sign=sign,
        snr_q10=q10,
        snr_q90=q90,
        iso_x=iso_x,
        iso_y=iso_y,
        vocab=ds.vocab,
    )
