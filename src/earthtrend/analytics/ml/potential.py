"""Inference of M2 TrendPotential (docs/PLAN_ANALYTICS.md section 11.3).

A model version is a directory ``models/potential/<version>/`` with:

* ``significance.txt``, ``sign.txt``, ``snr_q10.txt``, ``snr_q90.txt`` - LightGBM boosters;
* ``calibration.json`` - isotonic map of the significance score (x/y knots) and the vocab;
* ``config.yaml``, ``data_manifest.json``, ``metrics.json``, ``gates.json``, ``model_card.md``.

``models/potential/ACTIVE`` names the version that passed its gates. Without it (or without
``lightgbm`` installed) ``predict_potential`` returns an empty page with a
``fallback_reason``: the app then simply shows no hints (section 16: everything works
without models).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from earthtrend.analytics.ml.features import FEATURE_NAMES, Vocab, build_matrix, reason_for
from earthtrend.analytics.ml.potential_models import (
    PotentialPage,
    ReasonCode,
    RegionFeatures,
    TrendPotential,
    VariableInfo,
)
from earthtrend.analytics.models import Season

MODEL_NAME = "potential"
SIGN_MIN_CONFIDENCE = 0.6  # below -> expected_sign 0
N_REASONS = 3


@dataclass
class PotentialModel:
    version: str
    significance: Any  # lightgbm.Booster
    sign: Any
    snr_q10: Any
    snr_q90: Any
    iso_x: NDArray[np.float64]
    iso_y: NDArray[np.float64]
    vocab: Vocab

    # ------------------------------------------------------------ io

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.significance.save_model(str(directory / "significance.txt"))
        self.sign.save_model(str(directory / "sign.txt"))
        self.snr_q10.save_model(str(directory / "snr_q10.txt"))
        self.snr_q90.save_model(str(directory / "snr_q90.txt"))
        (directory / "calibration.json").write_text(
            json.dumps(
                {
                    "version": self.version,
                    "iso_x": self.iso_x.tolist(),
                    "iso_y": self.iso_y.tolist(),
                    "vocab": self.vocab.data,
                    "feature_names": list(FEATURE_NAMES),
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> PotentialModel:
        import lightgbm as lgb

        cal = json.loads((directory / "calibration.json").read_text(encoding="utf-8"))
        if cal["feature_names"] != list(FEATURE_NAMES):
            raise ValueError("model was trained on a different feature set")

        def booster(name: str) -> Any:
            return lgb.Booster(model_file=str(directory / f"{name}.txt"))

        return cls(
            version=cal["version"],
            significance=booster("significance"),
            sign=booster("sign"),
            snr_q10=booster("snr_q10"),
            snr_q90=booster("snr_q90"),
            iso_x=np.asarray(cal["iso_x"], dtype=np.float64),
            iso_y=np.asarray(cal["iso_y"], dtype=np.float64),
            vocab=Vocab(cal["vocab"]),
        )

    # ------------------------------------------------------------ prediction

    def calibrate(self, raw: NDArray[np.float64]) -> NDArray[np.float64]:
        if self.iso_x.size == 0:
            return raw
        return np.asarray(np.interp(raw, self.iso_x, self.iso_y))

    def predict_matrix(self, x: NDArray[np.float64]) -> dict[str, NDArray[np.float64]]:
        raw = np.asarray(self.significance.predict(x), dtype=np.float64)
        q10 = np.clip(np.asarray(self.snr_q10.predict(x), dtype=np.float64), 0, None)
        q90 = np.maximum(np.asarray(self.snr_q90.predict(x), dtype=np.float64), q10)
        return {
            "p_significant": self.calibrate(raw),
            "p_positive": np.asarray(self.sign.predict(x), dtype=np.float64),
            "snr_q10": q10,
            "snr_q90": q90,
        }

    def reasons(self, x: NDArray[np.float64]) -> list[list[ReasonCode]]:
        """Top positive SHAP contributions (LightGBM ``pred_contrib``) -> reason codes."""
        contrib = np.asarray(self.significance.predict(x, pred_contrib=True))[:, :-1]
        out: list[list[ReasonCode]] = []
        for row, c in zip(x, contrib, strict=True):
            # Regional reasons first; variable/season priors only fill the remaining slots,
            # so a hint says what about the *region* raises the chance (section 11.3).
            regional: list[ReasonCode] = []
            priors: list[ReasonCode] = []
            for j in np.argsort(-c):
                if c[j] <= 0:
                    break
                code = reason_for(FEATURE_NAMES[j], float(row[j]))
                if code is None:
                    continue
                bucket = priors if code in ("variable_prior", "season_prior") else regional
                if code not in bucket:
                    bucket.append(code)
            out.append((regional + priors)[:N_REASONS])
        return out


def _sign(p_pos: float) -> Literal[-1, 0, 1]:
    if p_pos >= SIGN_MIN_CONFIDENCE:
        return 1
    if p_pos <= 1 - SIGN_MIN_CONFIDENCE:
        return -1
    return 0


def predict_with(
    model: PotentialModel,
    region: RegionFeatures,
    variables: Sequence[VariableInfo],
    seasons: Sequence[Season] = ("annual",),
) -> list[TrendPotential]:
    rows = [(region, v, s) for v in variables for s in seasons]
    if not rows:
        return []
    x = build_matrix(rows, model.vocab)
    pred = model.predict_matrix(x)
    reasons = model.reasons(x)
    items = [
        TrendPotential(
            variable_id=var.variable_id,
            season=season,
            p_significant=float(np.clip(pred["p_significant"][k], 0, 1)),
            expected_sign=_sign(float(pred["p_positive"][k])),
            expected_snr=(float(pred["snr_q10"][k]), float(pred["snr_q90"][k])),
            top_reasons=reasons[k],
            model_version=model.version,
        )
        for k, (_, var, season) in enumerate(rows)
    ]
    items.sort(key=lambda t: -t.p_significant)
    return items


def models_root() -> Path:
    return Path(__file__).resolve().parents[4] / "models"


_CACHE: dict[str, PotentialModel] = {}


def active_model(root: Path | None = None) -> tuple[PotentialModel | None, str | None]:
    """(model, None) or (None, fallback_reason)."""
    base = (root or models_root()) / MODEL_NAME
    marker = base / "ACTIVE"
    if not marker.is_file():
        return None, "no_active_model"
    version = marker.read_text(encoding="utf-8").strip()
    vdir = base / version
    try:
        gates = json.loads((vdir / "gates.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "load_error"
    if gates.get("status") != "pass":
        return None, "gate_not_passed"
    key = str(vdir)
    if key not in _CACHE:
        try:
            _CACHE[key] = PotentialModel.load(vdir)
        except ImportError:
            return None, "lightgbm_not_installed"
        except (OSError, ValueError, KeyError):
            return None, "load_error"
    return _CACHE[key], None


def predict_potential(
    region: RegionFeatures,
    variables: Sequence[VariableInfo],
    seasons: Sequence[Season] = ("annual",),
    *,
    top_k: int | None = None,
    root: Path | None = None,
) -> PotentialPage:
    """Entry point for ``GET /api/v1/regions/{id}/potential``."""
    model, reason = active_model(root)
    if model is None:
        return PotentialPage(
            region_id=region.region_id, items=[], model_version=None, fallback_reason=reason
        )
    items = predict_with(model, region, variables, seasons)
    if top_k is not None:
        items = items[:top_k]
    return PotentialPage(region_id=region.region_id, items=items, model_version=model.version)


def clear_cache() -> None:
    _CACHE.clear()


__all__ = [
    "PotentialModel",
    "active_model",
    "clear_cache",
    "predict_potential",
    "predict_with",
]
