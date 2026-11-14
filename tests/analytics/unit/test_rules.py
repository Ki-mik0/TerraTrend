"""verdict_rules_v1: every row of the table in PLAN_ANALYTICS 6.8."""

import pytest

from earthtrend.analytics.evidence.rules import evaluate, load_ruleset
from earthtrend.analytics.models import EvidenceItem

RS = load_ruleset("verdict_rules_v1")
SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0, "na": 0.0}


def items(**status: str) -> list[EvidenceItem]:
    base = {
        "statistics": "pass",
        "magnitude": "pass",
        "witnesses": "pass",
        "robustness": "pass",
        "alibi": "pass",
        "quality": "pass",
    }
    base.update(status)
    return [EvidenceItem(key=k, status=v, score=SCORE[v]) for k, v in base.items()]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        ({}, "proven"),
        ({"alibi": "na"}, "proven"),
        ({"quality": "partial"}, "strong"),
        ({"witnesses": "na", "alibi": "na"}, "strong"),  # robustness + quality + magnitude
        ({"magnitude": "fail", "quality": "partial"}, "strong"),  # magnitude may fail
        ({"witnesses": "partial", "alibi": "partial", "quality": "partial"}, "likely"),
        ({"robustness": "fail"}, "likely"),
        ({"quality": "fail"}, "suspicious"),
        ({"statistics": "partial"}, "suspicious"),
        ({"statistics": "fail"}, "no_evidence"),
        ({"alibi": "fail"}, "likely"),  # a fail blocks strong; falls back to likely
    ],
)
def test_verdict_table(status: dict[str, str], verdict: str) -> None:
    assert evaluate(items(**status), RS)[0] == verdict


def test_strength_renormalizes_over_available_items() -> None:
    assert evaluate(items(), RS)[1] == 100
    # witnesses and alibi missing: still 100 when everything present passes
    assert evaluate(items(witnesses="na", alibi="na"), RS)[1] == 100
    # statistics partial: 30 * 0.5 of 100
    assert evaluate(items(statistics="partial"), RS)[1] == 85


def test_advisory_item_is_ignored() -> None:
    its = items(statistics="fail")
    its.append(EvidenceItem(key="ai_expert", status="pass", score=1.0, advisory=True))
    assert evaluate(its, RS) == evaluate(items(statistics="fail"), RS)


def test_ruleset_file_is_versioned() -> None:
    assert RS.ruleset == "verdict_rules_v1"
    assert sum(RS.weights.values()) == 100
    with pytest.raises(FileNotFoundError):
        load_ruleset("verdict_rules_v999")
