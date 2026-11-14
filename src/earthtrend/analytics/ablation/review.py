"""Manual review of statistics <-> AI disagreements (docs/PLAN_ANALYTICS.md 6.7, 9.5, 13.3).

A protocol whose advisory ``ai_expert`` item disagrees with the statistics carries the
caveat ``ai_disagrees``. A sample of those cases goes to a human reviewer; the labels tell
whether the AI should ever bind the verdict (``verdict_rules_v2``) and become hard
examples for retraining M1 (section 9.5).

Storage is the backend's (table ``ai_reviews``); this module only takes and returns models:
which cases to show first, how to summarise the labels, which labels become training data.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from earthtrend.analytics.models import Direction, EvidenceProtocol, ItemStatus, VerdictCode

ReviewOutcome = Literal["statistics_right", "ai_right", "both_wrong", "unclear"]
CauseCode = Literal[
    "sensor_change",  # instrument / satellite switch near the changepoint
    "processing_change",  # product version or algorithm change
    "real_regime_shift",  # a genuine abrupt change in the climate system
    "trend_too_short",  # the record is too short to tell
    "outlier_years",  # a few extreme years drive the reading
    "other",
]
OUTCOMES: tuple[ReviewOutcome, ...] = ("statistics_right", "ai_right", "both_wrong", "unclear")
SIGNIFICANT: frozenset[str] = frozenset({"proven", "strong"})
# AI readings that contradict a significant verdict most sharply (section 6.7: ``fail``).
OBJECTING_CLASSES: frozenset[str] = frozenset({"step", "no_trend"})
CONFIDENCE_BONUS = {"high": 10.0, "medium": 5.0, "low": 0.0}
Z95 = 1.959964


class ReviewCase(BaseModel):
    """One ``ai_disagrees`` case as shown to the reviewer."""

    case_key: str
    verdict: VerdictCode
    strength: int
    direction: Direction
    statistics_status: ItemStatus
    ai_status: ItemStatus
    ai_class: str
    ai_confidence: Literal["high", "medium", "low"]
    ai_details: dict[str, Any] = Field(default_factory=dict)  # the AiOpinion as stored
    priority: float  # higher first; see ``case_priority``


class ReviewLabel(BaseModel):
    """A reviewer's judgement of one case (backend table ``ai_reviews``)."""

    case_key: str
    outcome: ReviewOutcome
    artifact_found: bool = False  # the reviewer saw an instrument/processing artifact
    cause: CauseCode | None = None
    reviewer: str | None = None  # pseudonymous id, never a name


class ReviewSummary(BaseModel):
    n_labels: int
    n_cases: int  # after the majority vote per case
    counts: dict[str, int]
    ai_precision: float | None  # ai_right / (ai_right + statistics_right + both_wrong)
    ai_precision_ci95: tuple[float, float] | None  # Wilson
    artifact_share: float | None
    causes: dict[str, int]
    final: dict[str, ReviewOutcome]  # case_key -> outcome after the vote


# ---------------------------------------------------------------- queue


def case_priority(verdict: str, strength: int, ai_class: str, confidence: str) -> float:
    """Tier first, then strength (0-100), then AI confidence.

    Tier 2: a ``proven``/``strong`` verdict that the AI reads as ``step`` or ``no_trend``,
    the cases where a binding AI would change the answer most. Tier 1: other
    ``proven``/``strong`` disagreements. Tier 0: the rest.
    """
    sig = verdict in SIGNIFICANT
    tier = 2 if sig and ai_class in OBJECTING_CLASSES else 1 if sig else 0
    return 200.0 * tier + float(strength) + CONFIDENCE_BONUS.get(confidence, 0.0)


def disagreement_cases(protocols: Mapping[str, EvidenceProtocol]) -> list[ReviewCase]:
    """All protocols with the caveat ``ai_disagrees`` and an ``ai_expert`` item."""
    out: list[ReviewCase] = []
    for key, pr in protocols.items():
        if "ai_disagrees" not in pr.caveats:
            continue
        ai, stat = pr.item("ai_expert"), pr.item("statistics")
        if ai is None:
            continue
        d = ai.details
        cls = str(d.get("predicted_class", "unknown"))
        conf = d.get("confidence", "low")
        conf = conf if conf in CONFIDENCE_BONUS else "low"
        out.append(
            ReviewCase(
                case_key=key,
                verdict=pr.verdict,
                strength=pr.strength,
                direction=pr.direction,
                statistics_status=stat.status if stat is not None else "na",
                ai_status=ai.status,
                ai_class=cls,
                ai_confidence=conf,
                ai_details=dict(d),
                priority=case_priority(pr.verdict, pr.strength, cls, conf),
            )
        )
    return out


def review_queue(
    protocols: Mapping[str, EvidenceProtocol], k: int, seed: int = 0
) -> list[ReviewCase]:
    """Up to ``k`` disagreement cases for review, highest priority first.

    Stratified by AI class: first every class gets its best case (classes in order of that
    case's priority, so rare classes such as ``accelerating`` are not crowded out by many
    ``step`` cases), then the remaining slots go by priority. Ties in priority are broken
    by a reproducible shuffle from ``seed``.
    """
    if k <= 0:
        return []
    cases = disagreement_cases(protocols)
    rng = np.random.default_rng(seed)
    shuffled = [cases[i] for i in rng.permutation(len(cases))]
    ranked = sorted(shuffled, key=lambda c: -c.priority)  # stable: shuffle breaks ties

    chosen: list[ReviewCase] = []
    seen_classes: set[str] = set()
    for c in ranked:  # one per class
        if len(chosen) >= k:
            break
        if c.ai_class not in seen_classes:
            seen_classes.add(c.ai_class)
            chosen.append(c)
    taken = {c.case_key for c in chosen}
    for c in ranked:
        if len(chosen) >= k:
            break
        if c.case_key not in taken:
            chosen.append(c)
            taken.add(c.case_key)
    return sorted(chosen, key=lambda c: (-c.priority, c.case_key))


# ---------------------------------------------------------------- summary


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes out of n; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def _final_outcomes(labels: Iterable[ReviewLabel]) -> dict[str, ReviewOutcome]:
    """Majority vote per case; a tie for the top outcome gives ``unclear``."""
    by_case: dict[str, list[ReviewOutcome]] = {}
    for lab in labels:
        by_case.setdefault(lab.case_key, []).append(lab.outcome)
    final: dict[str, ReviewOutcome] = {}
    for key, outs in by_case.items():
        top = Counter(outs).most_common()
        final[key] = top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else "unclear"
    return final


def summarize_reviews(labels: Sequence[ReviewLabel]) -> ReviewSummary:
    """AI precision on disagreements with a Wilson 95% CI.

    Precision = ``ai_right / (ai_right + statistics_right + both_wrong)``: in a
    ``both_wrong`` case the AI was wrong too. ``unclear`` cases are counted but left out.
    A case with several reviewers is decided by majority (ties -> ``unclear``); it counts
    as an artifact when any reviewer found one.
    """
    final = _final_outcomes(labels)
    counts = Counter(final.values())
    decided = counts["ai_right"] + counts["statistics_right"] + counts["both_wrong"]
    artifact: dict[str, bool] = {}
    causes: Counter[str] = Counter()
    for lab in labels:
        artifact[lab.case_key] = artifact.get(lab.case_key, False) or lab.artifact_found
        if lab.cause is not None:
            causes[lab.cause] += 1
    return ReviewSummary(
        n_labels=len(labels),
        n_cases=len(final),
        counts={o: counts[o] for o in OUTCOMES},
        ai_precision=counts["ai_right"] / decided if decided else None,
        ai_precision_ci95=wilson(counts["ai_right"], decided),
        artifact_share=float(np.mean(list(artifact.values()))) if artifact else None,
        causes=dict(sorted(causes.items())),
        final=final,
    )


# ---------------------------------------------------------------- hard examples


def _target_class(case: ReviewCase, outcome: ReviewOutcome, artifact: bool) -> str | None:
    if artifact and outcome != "statistics_right":
        return "step"  # an instrument/processing jump is exactly what M1 should call a step
    if outcome == "ai_right":
        return case.ai_class
    if outcome == "statistics_right":
        return "linear" if case.verdict in SIGNIFICANT else "no_trend"
    return None  # both_wrong without an artifact, unclear: no reliable target


def hard_examples(
    labels: Sequence[ReviewLabel], cases: Sequence[ReviewCase]
) -> list[dict[str, Any]]:
    """Reviewed disagreements as training examples for M1 retraining (section 9.5).

    Target class: an artifact found (unless the statistics were judged right) -> ``step``;
    ``ai_right`` -> the AI class; ``statistics_right`` -> ``linear`` for a significant
    verdict, else ``no_trend``. ``unclear`` and ``both_wrong`` without an artifact are
    skipped. ``ai_was_wrong`` marks the examples that correct the current model. The series
    itself is joined by ``case_key`` in the training pipeline.
    """
    final = _final_outcomes(labels)
    artifact: dict[str, bool] = {}
    cause: dict[str, str] = {}
    for lab in labels:
        artifact[lab.case_key] = artifact.get(lab.case_key, False) or lab.artifact_found
        if lab.cause is not None:
            cause.setdefault(lab.case_key, lab.cause)
    out: list[dict[str, Any]] = []
    for c in cases:
        outcome = final.get(c.case_key)
        if outcome is None:
            continue
        target = _target_class(c, outcome, artifact.get(c.case_key, False))
        if target is None:
            continue
        out.append(
            {
                "case_key": c.case_key,
                "target_class": target,
                "ai_class": c.ai_class,
                "ai_was_wrong": target != c.ai_class,
                "verdict": c.verdict,
                "outcome": outcome,
                "artifact_found": artifact.get(c.case_key, False),
                "cause": cause.get(c.case_key),
                "source": "ai_review",
            }
        )
    return out
