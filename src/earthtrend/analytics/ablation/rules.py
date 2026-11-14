"""Candidate ``verdict_rules_v2`` rulesets (docs/PLAN_ANALYTICS.md sections 6.8, 13.3).

Candidates are derived from ``verdict_rules_v1`` in code, so any change to v1 carries over
and the only difference under test is the role of ``ai_expert``:

* ``veto`` - an AI ``fail`` (step / likely artifact, or "no trend" against significant
  statistics) blocks ``proven`` and ``strong``; the case falls through to the next rule.
* ``strict`` - ``proven`` needs the AI to agree (``pass`` or no opinion); ``strong`` is
  blocked by an AI ``fail``.

The ``ai_expert`` weight is 0, so ``strength`` is unchanged and the ablation measures the
verdict effect alone. A missing opinion (``na``) never blocks anything: without M1 every
candidate reproduces v1 exactly (tested).
"""

from __future__ import annotations

from typing import Literal

from earthtrend.analytics.evidence.rules import Ruleset, VerdictRule, load_ruleset
from earthtrend.analytics.models import EvidenceItem

Variant = Literal["veto", "strict"]
VARIANTS: tuple[Variant, ...] = ("veto", "strict")
AI_KEY = "ai_expert"


def candidate_ruleset(variant: Variant, base: str = "verdict_rules_v1") -> Ruleset:
    v1 = load_ruleset(base)
    rules: list[VerdictRule] = []
    for r in v1.verdicts:
        allowed: list[str] | None = None
        if r.code == "proven":
            allowed = ["pass", "na"] if variant == "strict" else ["pass", "partial", "na"]
        elif r.code == "strong":
            allowed = ["pass", "partial", "na"]
        if allowed is None:
            rules.append(r)
        else:
            rules.append(r.model_copy(update={"all": {**r.all, AI_KEY: allowed}}))
    return Ruleset(
        ruleset=f"verdict_rules_v2_{variant}",
        weights={**v1.weights, AI_KEY: 0.0},
        status_score=v1.status_score,
        verdicts=rules,
    )


def binding_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """The same items with ``ai_expert`` made binding (``advisory=False``) for v2."""
    return [i.model_copy(update={"advisory": False}) if i.key == AI_KEY else i for i in items]
