"""Evaluation harness and quality gate for M3 VarSearch (PLAN_ANALYTICS 11.4, 11.6).

Metrics per language (UA and EN separately):
* Recall@5 - share of queries with at least one relevant variable in the top 5;
* MRR - mean of 1 / rank of the first relevant variable (0 if none in the catalog ranking).

Systems compared: `bm25`, `base_dense`, `base_hybrid` (the honest baseline of 11.4: base
model + BM25), `tuned_dense`, `tuned_hybrid` (what ships).

Gate (11.4): on the *human* test, `tuned_hybrid - base_hybrid >= 0.05` for both Recall@5 and
MRR, separately for UA and EN. Without a real human test the gate is `not_evaluated`, and an
`not_evaluated` or `fail` model is never served (`ml/varsearch.py` falls back to BM25).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from earthtrend.analytics.ml.varsearch import Retriever
from earthtrend.analytics.ml.varsearch_catalog import LANGS

GATE_MARGIN = 0.05
GATE_METRICS = ("recall@5", "mrr")
BASELINE = "base_hybrid"
CANDIDATE = "tuned_hybrid"
GateStatus = Literal["pass", "fail", "not_evaluated"]


@dataclass(frozen=True)
class EvalQuery:
    query: str
    lang: str
    relevant: tuple[str, ...]


def recall_at_k(ranking: Sequence[str], relevant: Sequence[str], k: int = 5) -> float:
    rel = set(relevant)
    return 1.0 if any(r in rel for r in ranking[:k]) else 0.0


def reciprocal_rank(ranking: Sequence[str], relevant: Sequence[str]) -> float:
    rel = set(relevant)
    for i, r in enumerate(ranking, start=1):
        if r in rel:
            return 1.0 / i
    return 0.0


def evaluate_retriever(retriever: Retriever, queries: Sequence[EvalQuery]) -> dict[str, Any]:
    """{lang: {"n", "recall@1", "recall@5", "mrr"}} plus "all"."""
    rankings = retriever.rank_many([q.query for q in queries])
    groups: dict[str, list[tuple[list[str], EvalQuery]]] = {"all": []}
    for ranking, q in zip(rankings, queries, strict=True):
        groups["all"].append((ranking, q))
        groups.setdefault(q.lang, []).append((ranking, q))
    out: dict[str, Any] = {}
    for name, items in groups.items():
        n = len(items)
        if n == 0:
            out[name] = {"n": 0}
            continue
        out[name] = {
            "n": n,
            "recall@1": sum(recall_at_k(r, q.relevant, 1) for r, q in items) / n,
            "recall@5": sum(recall_at_k(r, q.relevant, 5) for r, q in items) / n,
            "mrr": sum(reciprocal_rank(r, q.relevant) for r, q in items) / n,
        }
    return out


def evaluate_systems(
    systems: Mapping[str, Retriever], queries: Sequence[EvalQuery]
) -> dict[str, dict[str, Any]]:
    return {name: evaluate_retriever(r, queries) for name, r in systems.items()}


def quality_gate(
    human_metrics: Mapping[str, Mapping[str, Any]] | None,
    *,
    reason: str | None = None,
    margin: float = GATE_MARGIN,
) -> dict[str, Any]:
    """gates.json content. `human_metrics` is `evaluate_systems` output on the human test,
    or None when the human test does not exist (-> `not_evaluated`)."""
    if human_metrics is None:
        return {
            "model": "varsearch",
            "overall": "not_evaluated",
            "reason": reason or "human test set missing (human_test/human_test.csv)",
            "criteria": [],
            "margin": margin,
            "baseline": BASELINE,
            "candidate": CANDIDATE,
        }
    criteria: list[dict[str, Any]] = []
    for lang in LANGS:
        base = human_metrics[BASELINE].get(lang, {})
        cand = human_metrics[CANDIDATE].get(lang, {})
        for metric in GATE_METRICS:
            if not base.get("n") or not cand.get("n"):
                criteria.append(
                    {"lang": lang, "metric": metric, "status": "not_evaluated", "reason": "n=0"}
                )
                continue
            delta = float(cand[metric]) - float(base[metric])
            criteria.append(
                {
                    "lang": lang,
                    "metric": metric,
                    "baseline": float(base[metric]),
                    "candidate": float(cand[metric]),
                    "delta": delta,
                    "required": margin,
                    "n": int(cand["n"]),
                    "status": "pass" if delta >= margin - 1e-9 else "fail",
                }
            )
    statuses = {c["status"] for c in criteria}
    overall: GateStatus
    if "fail" in statuses:
        overall = "fail"
    elif "not_evaluated" in statuses:
        overall = "not_evaluated"
    else:
        overall = "pass"
    return {
        "model": "varsearch",
        "overall": overall,
        "reason": reason,
        "criteria": criteria,
        "margin": margin,
        "baseline": BASELINE,
        "candidate": CANDIDATE,
    }
