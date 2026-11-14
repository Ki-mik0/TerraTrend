"""Verdict rules as data (section 6.8): load a YAML ruleset and evaluate protocol items."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from earthtrend.analytics.models import EvidenceItem, VerdictCode

RULES_DIR = Path(__file__).parent / "rulesets"


class VerdictRule(BaseModel):
    code: VerdictCode
    all: dict[str, list[str]] = Field(default_factory=dict)
    any: dict[str, list[str]] = Field(default_factory=dict)
    min_pass: int | None = None
    no_fail_except: list[str] | None = None


class Ruleset(BaseModel):
    ruleset: str
    weights: dict[str, float]
    status_score: dict[str, float]
    verdicts: list[VerdictRule]


@lru_cache(maxsize=4)
def load_ruleset(name: str = "verdict_rules_v1") -> Ruleset:
    path = RULES_DIR / f"{name}.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    rs = Ruleset.model_validate(data)
    if rs.ruleset != name:
        raise ValueError(f"{path.name} declares ruleset {rs.ruleset!r}")
    return rs


def _matches(rule: VerdictRule, status: dict[str, str]) -> bool:
    if any(status.get(k, "na") not in allowed for k, allowed in rule.all.items()):
        return False
    if rule.any and not any(status.get(k, "na") in allowed for k, allowed in rule.any.items()):
        return False
    if rule.min_pass is not None:
        others = sum(1 for k, s in status.items() if k != "statistics" and s == "pass")
        if others < rule.min_pass:
            return False
    if rule.no_fail_except is not None:
        if any(s == "fail" for k, s in status.items() if k not in rule.no_fail_except):
            return False
    return True


def evaluate(items: list[EvidenceItem], ruleset: Ruleset) -> tuple[VerdictCode, int]:
    """Return (verdict, strength). Advisory items are ignored."""
    status: dict[str, str] = {
        i.key: i.status for i in items if not i.advisory and i.key in ruleset.weights
    }
    verdict: VerdictCode = "no_evidence"
    for rule in ruleset.verdicts:
        if _matches(rule, status):
            verdict = rule.code
            break
    num = den = 0.0
    for key, st in status.items():
        if st == "na":
            continue
        w = ruleset.weights[key]
        num += w * ruleset.status_score[st]
        den += w
    strength = round(100 * num / den) if den > 0 else 0
    return verdict, strength
