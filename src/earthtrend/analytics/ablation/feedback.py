"""Feedback loop for the advisory models (docs/PLAN_ANALYTICS.md sections 11.3, 6.7, 13.3).

Every hint a model gives is later checked against what the real analysis found:

* **M2 TrendPotential** (backend table ``potential_feedback``): ``p_significant`` against
  whether the real case reached a significant verdict;
* **M1 TrendNet**: its opinion against the final verdict of the protocol.

The backend stores the records; this module only turns them into quality numbers per
(model, version) over a rolling window of the most recent records and flags drift.
Only numpy and pydantic: the monitor must stay cheap enough to run on every request.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

from earthtrend.analytics.models import AiOpinion, VerdictCode

DriftCode = Literal["calibration_drift", "brier_worse_than_baseline", "too_few_records"]

ECE_MAX = 0.05  # same gate as M2 validation (section 11.3)
ECE_BINS = 10
MIN_RECORDS = 200  # below this ECE is too noisy to call drift
DEFAULT_WINDOW = 500
SIGNIFICANT_VERDICTS: frozenset[str] = frozenset({"proven", "strong"})
# M1 classes that mean "a real trend is present"; ``step`` is a likely artifact (6.7).
M1_TREND_CLASSES: frozenset[str] = frozenset({"linear", "accelerating", "trend_plus_step"})


class PredictionRecord(BaseModel):
    """One model hint and the outcome the real analysis produced for it.

    ``p`` is the predicted probability of the positive outcome (``actual``). Class models
    may also carry ``predicted_class`` / ``actual_class``; agreement then compares the
    classes, otherwise it compares ``p >= 0.5`` with ``actual``.
    """

    model: str = Field(min_length=1)  # "m1_trendnet", "m2_potential", ...
    model_version: str = Field(min_length=1)
    key: str = Field(min_length=1)  # case / (region, variable, season) key
    p: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_class: str | None = None
    actual: bool
    actual_class: str | None = None
    at: datetime

    @model_validator(mode="after")
    def _has_prediction(self) -> PredictionRecord:
        if self.p is None and self.predicted_class is None:
            raise ValueError("a record needs p or predicted_class")
        return self

    @property
    def agrees(self) -> bool:
        if self.predicted_class is not None and self.actual_class is not None:
            return self.predicted_class == self.actual_class
        if self.p is not None:
            return (self.p >= 0.5) == self.actual
        # class only, no actual class: positive class iff it is a trend class
        return (self.predicted_class in M1_TREND_CLASSES) == self.actual


class MonitorReport(BaseModel):
    """Quality of one (model, version) over its latest window of records."""

    model: str
    model_version: str
    n: int  # records in the window
    n_total: int  # all records of this model version
    window_start: datetime | None
    window_end: datetime | None
    brier: float | None  # None when no record in the window has p
    ece: float | None
    agreement: float | None
    base_rate: float | None  # share of positive outcomes in the window
    baseline_brier: float | None  # Brier of always predicting the frequency baseline
    codes: list[DriftCode]


# ---------------------------------------------------------------- adapters


def from_potential(
    *,
    key: str,
    model_version: str,
    p_significant: float,
    verdict: VerdictCode,
    at: datetime,
) -> PredictionRecord:
    """An M2 hint checked by the real analysis: positive = verdict strong/proven."""
    return PredictionRecord(
        model="m2_potential",
        model_version=model_version,
        key=key,
        p=p_significant,
        actual=verdict in SIGNIFICANT_VERDICTS,
        at=at,
    )


def from_ai_opinion(
    opinion: AiOpinion, *, key: str, verdict: VerdictCode, at: datetime
) -> PredictionRecord:
    """An M1 opinion against the final verdict.

    ``p`` is the probability mass M1 puts on a real trend (linear, accelerating,
    trend_plus_step); the outcome is a strong/proven verdict. So agreement means "M1 saw a
    trend exactly when the protocol proved one", the same reading as ``ai_disagrees``.
    """
    p = float(sum(v for k, v in opinion.class_probs.items() if k in M1_TREND_CLASSES))
    return PredictionRecord(
        model="m1_trendnet",
        model_version=opinion.model_version,
        key=key,
        p=min(max(p, 0.0), 1.0),
        predicted_class=opinion.predicted_class,
        actual=verdict in SIGNIFICANT_VERDICTS,
        at=at,
    )


# ---------------------------------------------------------------- metrics


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y.astype(float)) ** 2))


def ece(p: np.ndarray, y: np.ndarray, bins: int = ECE_BINS) -> float:
    """Expected calibration error with equal-width bins (as in M2 validation)."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    yf = y.astype(float)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += float(m.mean()) * abs(float(p[m].mean()) - float(yf[m].mean()))
    return total


def _report(
    model: str,
    version: str,
    recs: Sequence[PredictionRecord],
    window: int,
    min_records: int,
    baseline_rate: float | None,
) -> MonitorReport:
    ordered = sorted(recs, key=lambda r: (r.at, r.key))
    win = ordered[-window:]
    codes: list[DriftCode] = []
    if len(win) < min_records:
        codes.append("too_few_records")

    prob = [r for r in win if r.p is not None]
    b = e = base = base_brier = None
    if prob:
        p = np.array([r.p for r in prob], dtype=float)
        y = np.array([r.actual for r in prob], dtype=bool)
        b, e = brier(p, y), ece(p, y)
        base = float(y.mean())
        rate = base if baseline_rate is None else baseline_rate
        base_brier = brier(np.full(len(y), rate), y)
        if len(prob) >= min_records:
            if e > ECE_MAX:
                codes.append("calibration_drift")
            if b > base_brier:
                codes.append("brier_worse_than_baseline")

    return MonitorReport(
        model=model,
        model_version=version,
        n=len(win),
        n_total=len(ordered),
        window_start=win[0].at if win else None,
        window_end=win[-1].at if win else None,
        brier=b,
        ece=e,
        agreement=float(np.mean([r.agrees for r in win])) if win else None,
        base_rate=base,
        baseline_brier=base_brier,
        codes=codes,
    )


def monitor(
    records: Iterable[PredictionRecord],
    window: int = DEFAULT_WINDOW,
    *,
    min_records: int = MIN_RECORDS,
    baseline_rates: dict[str, float] | None = None,
) -> list[MonitorReport]:
    """Quality per (model, version) over its ``window`` most recent records.

    Drift codes (only judged once the window holds ``min_records`` probability records):

    * ``calibration_drift`` — ECE (10 bins) > 0.05;
    * ``brier_worse_than_baseline`` — the model's Brier is worse than always predicting
      the frequency baseline: ``baseline_rates[model]`` when given (e.g. the training
      base rate), otherwise the positive share observed in the window itself;
    * ``too_few_records`` — fewer than ``min_records`` records in the window.

    Reports are sorted by (model, version).
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    groups: dict[tuple[str, str], list[PredictionRecord]] = defaultdict(list)
    for r in records:
        groups[(r.model, r.model_version)].append(r)
    rates = baseline_rates or {}
    return [
        _report(model, version, groups[(model, version)], window, min_records, rates.get(model))
        for model, version in sorted(groups)
    ]
