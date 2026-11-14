"""Stage A11: manual review of ``ai_disagrees`` cases (PLAN 6.7, 9.5, 13.3)."""

from __future__ import annotations

import pytest

from earthtrend.analytics.ablation import (
    ReviewLabel,
    hard_examples,
    review_queue,
    summarize_reviews,
)
from earthtrend.analytics.ablation.review import case_priority, disagreement_cases, wilson
from earthtrend.analytics.models import EvidenceItem, EvidenceProtocol


def _proto(
    verdict: str, strength: int, ai_class: str | None, conf: str = "high", disagrees: bool = True
) -> EvidenceProtocol:
    items = [EvidenceItem(key="statistics", status="pass", score=1.0)]
    if ai_class is not None:
        items.append(
            EvidenceItem(
                key="ai_expert",
                status="fail" if ai_class in ("step", "no_trend") else "partial",
                score=0.0,
                advisory=True,
                details={"predicted_class": ai_class, "confidence": conf},
            )
        )
    return EvidenceProtocol(
        items=items,
        verdict=verdict,
        strength=strength,
        ruleset="verdict_rules_v1",
        direction="increasing",
        caveats=["ai_disagrees"] if disagrees else [],
    )


def _protocols() -> dict[str, EvidenceProtocol]:
    ps = {f"step{i}": _proto("strong", 60 + i, "step") for i in range(10)}
    ps |= {f"lin{i}": _proto("likely", 50 + i, "linear", "medium") for i in range(5)}
    ps["acc"] = _proto("suspicious", 20, "accelerating", "low")  # rare class, low priority
    ps["top"] = _proto("proven", 95, "no_trend")
    ps["agree"] = _proto("proven", 99, "linear", disagrees=False)  # no caveat
    ps["no_ai"] = _proto("strong", 80, None)  # caveat without an ai item is ignored
    return ps


def test_priority_tiers() -> None:
    assert case_priority("proven", 10, "step", "low") > case_priority(
        "strong", 99, "linear", "high"
    )
    assert case_priority("strong", 50, "linear", "low") > case_priority(
        "likely", 99, "step", "high"
    )
    assert case_priority("strong", 70, "step", "high") > case_priority("strong", 70, "step", "low")


def test_only_disagreements_with_ai_item_are_cases() -> None:
    keys = {c.case_key for c in disagreement_cases(_protocols())}
    assert "agree" not in keys and "no_ai" not in keys
    assert len(keys) == 17


def test_queue_puts_objections_to_strong_verdicts_first_and_keeps_rare_classes() -> None:
    q = review_queue(_protocols(), k=5, seed=1)
    assert len(q) == 5
    assert q[0].case_key == "top"
    assert [c.priority for c in q] == sorted((c.priority for c in q), reverse=True)
    classes = {c.ai_class for c in q}
    assert classes == {"no_trend", "step", "linear", "accelerating"}  # stratified
    assert sum(c.ai_class == "step" for c in q) == 2  # the free slot goes by priority
    assert next(c for c in q if c.ai_class == "step").case_key == "step9"


def test_queue_is_reproducible_and_bounded() -> None:
    ps = {f"s{i}": _proto("strong", 70, "step") for i in range(20)}  # all tied
    a = [c.case_key for c in review_queue(ps, k=4, seed=7)]
    assert a == [c.case_key for c in review_queue(ps, k=4, seed=7)]
    assert review_queue(ps, k=0) == []
    assert len(review_queue(ps, k=100)) == 20


def test_case_fields_come_from_protocol() -> None:
    [c] = [c for c in review_queue(_protocols(), k=20) if c.case_key == "top"]
    assert c.verdict == "proven" and c.statistics_status == "pass" and c.ai_status == "fail"
    assert c.ai_confidence == "high" and c.ai_details["predicted_class"] == "no_trend"


def test_wilson() -> None:
    assert wilson(0, 0) is None
    lo, hi = wilson(8, 10)  # type: ignore[misc]
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert wilson(10, 10)[1] == pytest.approx(1.0)  # type: ignore[index]


def test_summary_majority_vote_and_precision() -> None:
    labels = [
        ReviewLabel(case_key="a", outcome="ai_right", artifact_found=True, cause="sensor_change"),
        ReviewLabel(case_key="a", outcome="ai_right", reviewer="r2"),
        ReviewLabel(case_key="a", outcome="statistics_right", reviewer="r3"),
        ReviewLabel(case_key="b", outcome="statistics_right"),
        ReviewLabel(case_key="c", outcome="ai_right"),
        ReviewLabel(case_key="c", outcome="statistics_right"),  # tie -> unclear
        ReviewLabel(case_key="d", outcome="both_wrong"),
    ]
    s = summarize_reviews(labels)
    assert s.n_labels == 7 and s.n_cases == 4
    assert s.final == {"a": "ai_right", "b": "statistics_right", "c": "unclear", "d": "both_wrong"}
    assert s.counts == {"statistics_right": 1, "ai_right": 1, "both_wrong": 1, "unclear": 1}
    assert s.ai_precision == pytest.approx(1 / 3)
    assert (
        s.ai_precision_ci95 is not None and s.ai_precision_ci95[0] < 1 / 3 < s.ai_precision_ci95[1]
    )
    assert s.artifact_share == pytest.approx(0.25)
    assert s.causes == {"sensor_change": 1}


def test_summary_of_nothing() -> None:
    s = summarize_reviews([])
    assert s.n_cases == 0 and s.ai_precision is None and s.ai_precision_ci95 is None


def test_hard_examples_targets() -> None:
    ps = {
        "art": _proto("strong", 80, "no_trend"),
        "air": _proto("likely", 50, "accelerating"),
        "str": _proto("proven", 90, "step"),
        "strns": _proto("suspicious", 30, "linear"),
        "bw": _proto("strong", 70, "step"),
        "unc": _proto("strong", 70, "step"),
        "unreviewed": _proto("strong", 70, "step"),
    }
    cases = review_queue(ps, k=10)
    labels = [
        ReviewLabel(
            case_key="art", outcome="both_wrong", artifact_found=True, cause="sensor_change"
        ),
        ReviewLabel(case_key="air", outcome="ai_right"),
        ReviewLabel(case_key="str", outcome="statistics_right"),
        ReviewLabel(case_key="strns", outcome="statistics_right"),
        ReviewLabel(case_key="bw", outcome="both_wrong"),
        ReviewLabel(case_key="unc", outcome="unclear"),
    ]
    ex = {e["case_key"]: e for e in hard_examples(labels, cases)}
    assert set(ex) == {"art", "air", "str", "strns"}
    assert ex["art"]["target_class"] == "step" and ex["art"]["ai_was_wrong"]
    assert ex["art"]["cause"] == "sensor_change"
    assert ex["air"]["target_class"] == "accelerating" and not ex["air"]["ai_was_wrong"]
    assert ex["str"]["target_class"] == "linear"
    assert ex["strns"]["target_class"] == "no_trend"
    assert all(e["source"] == "ai_review" for e in ex.values())
