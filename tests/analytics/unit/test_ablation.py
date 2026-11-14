"""Stage A11: verdict ablation v1 vs v2 candidates (PLAN_ANALYTICS 6.8, 13.3)."""

from __future__ import annotations

from typing import Any

import pytest

from earthtrend.analytics.ablation.decision import decide_v2, report_markdown, would_accept
from earthtrend.analytics.ablation.rules import VARIANTS, binding_items, candidate_ruleset
from earthtrend.analytics.ablation.study import (
    DEFAULT_SCENARIOS,
    Scenario,
    SimulatedOracle,
    mcnemar_p,
    run_ablation,
    run_case,
)
from earthtrend.analytics.evidence.rules import evaluate, load_ruleset
from earthtrend.analytics.models import EvidenceItem


def _items(**status: str) -> list[EvidenceItem]:
    return [
        EvidenceItem(key=k, status=s, score=0.5, advisory=(k == "ai_expert"))
        for k, s in status.items()
    ]


ALL_PASS = {
    "statistics": "pass",
    "magnitude": "pass",
    "witnesses": "pass",
    "robustness": "pass",
    "alibi": "na",
    "quality": "pass",
}


# ---------------------------------------------------------------- rules


@pytest.mark.parametrize("variant", VARIANTS)
def test_candidate_equals_v1_without_ai(variant: str) -> None:
    v1 = load_ruleset("verdict_rules_v1")
    cand = candidate_ruleset(variant)  # type: ignore[arg-type]
    for status in (
        ALL_PASS,
        {**ALL_PASS, "witnesses": "partial"},
        {**ALL_PASS, "statistics": "fail"},
    ):
        items = binding_items(_items(**status))
        assert evaluate(items, cand) == evaluate(items, v1)


def test_ai_fail_blocks_proven_and_strong() -> None:
    items = binding_items(_items(**ALL_PASS, ai_expert="fail"))
    assert evaluate(items, load_ruleset("verdict_rules_v1"))[0] == "proven"  # v1 ignores AI
    for v in VARIANTS:
        verdict, strength = evaluate(items, candidate_ruleset(v))
        assert verdict == "likely"
        assert strength == evaluate(items, load_ruleset("verdict_rules_v1"))[1]  # weight 0


def test_strict_needs_ai_pass_for_proven() -> None:
    items = binding_items(_items(**ALL_PASS, ai_expert="partial"))
    assert evaluate(items, candidate_ruleset("veto"))[0] == "proven"
    assert evaluate(items, candidate_ruleset("strict"))[0] == "strong"


def test_v1_still_ignores_advisory_ai() -> None:
    items = _items(**ALL_PASS, ai_expert="fail")  # advisory=True
    assert evaluate(items, candidate_ruleset("veto"))[0] == "proven"


# ---------------------------------------------------------------- study


def test_no_ai_means_v2_equals_v1() -> None:
    sc = Scenario("sensor_step_no_witness", "step", step_size=1.5, witness=False)
    out = run_case(sc, 0, lambda *a: None)
    assert out.ai_status is None
    assert all(out.v2[v] == out.v1 for v in VARIANTS)


def test_perfect_ai_catches_instrument_step_without_witness() -> None:
    sc = Scenario("sensor_step_no_witness", "step", step_size=1.5, witness=False)
    outs, s = run_ablation(SimulatedOracle(accuracy=1.0), n_per_scenario=6, scenarios=[sc])
    assert s["by_scenario"][sc.name]["v1"] >= 0.5  # v1 is fooled by the step
    for v in VARIANTS:
        assert s["by_scenario"][sc.name][v] == 0.0
        assert s["variants"][v]["false_added"] == 0


def test_mcnemar() -> None:
    assert mcnemar_p(0, 0) == 1.0
    assert mcnemar_p(10, 0) == pytest.approx(2 * 0.5**10)
    assert mcnemar_p(5, 5) == 1.0


def test_default_scenarios_cover_both_truths() -> None:
    assert {s.positive for s in DEFAULT_SCENARIOS} == {True, False}
    assert any(s.truth == "step" and not s.witness for s in DEFAULT_SCENARIOS)


# ---------------------------------------------------------------- decision


def _summary(v1f: float, v1p: float, vf: float, vp: float, **kw: Any) -> dict[str, Any]:
    var = {
        "false_rate": vf,
        "false_on_negatives": vf,
        "power": vp,
        "false_removed": kw.get("removed", 30),
        "false_added": kw.get("added", 0),
        "hits_lost": kw.get("lost", 0),
        "hits_gained": 0,
        "p_false": kw.get("p_false", 1e-6),
        "p_power": kw.get("p_power", 1.0),
    }
    return {
        "ai_coverage": kw.get("coverage", 1.0),
        "v1": {"false_rate": v1f, "false_on_negatives": v1f, "power": v1p},
        "variants": {v: dict(var) for v in VARIANTS},
        "by_scenario": {
            "x": {
                "metric": "false_rate",
                "v1": v1f,
                **{v: vf for v in VARIANTS},
                "ai_disagrees": 0.1,
            }
        },
    }


def test_accept_when_fewer_false_and_power_kept() -> None:
    d = decide_v2(_summary(0.10, 0.80, 0.02, 0.79), "m1:1.0")
    assert d.status == "accept"
    assert d.chosen in {f"verdict_rules_v2_{v}" for v in VARIANTS}


def test_reject_on_power_drop() -> None:
    d = decide_v2(_summary(0.10, 0.80, 0.02, 0.70, lost=20, p_power=1e-4), "m1:1.0")
    assert d.status == "reject"
    assert all("power_drop_too_large" in c.reasons for c in d.checks)


def test_reject_when_reduction_not_significant() -> None:
    d = decide_v2(_summary(0.10, 0.80, 0.09, 0.80, removed=2, p_false=0.5), "m1:1.0")
    assert d.status == "reject"


def test_not_evaluated_without_model_or_with_simulated_oracle() -> None:
    assert decide_v2(_summary(0.1, 0.8, 0.0, 0.8, coverage=0.0), "m1:none").reasons == [
        "no_ai_opinions"
    ]
    d = decide_v2(_summary(0.1, 0.8, 0.0, 0.8), "simulated(accuracy=0.9)")
    assert d.status == "not_evaluated"
    assert would_accept(_summary(0.1, 0.8, 0.0, 0.8))


def test_report_renders() -> None:
    s = _summary(0.10, 0.80, 0.02, 0.79)
    md = report_markdown(
        decide_v2(s, "m1:1.0"),
        s,
        [
            {
                "accuracy": 0.9,
                "v1_false": 0.1,
                "v2_false": 0.02,
                "v1_power": 0.8,
                "v2_power": 0.79,
                "would_accept": True,
            }
        ],
        50,
    )
    assert "**Decision: ACCEPT**" in md
    assert "How good must M1 be?" in md


def test_cli_writes_report(tmp_path: Any) -> None:
    from earthtrend.analytics.ablation.__main__ import main

    sc_n = "1"
    assert main(["--oracle", "simulated", "--n", sc_n, "--out", str(tmp_path)]) == 0
    assert (
        (tmp_path / "ablation_v2.md").read_text(encoding="utf-8").startswith("# Verdict ablation")
    )
    assert (tmp_path / "ablation_v2.json").is_file()


@pytest.mark.slow
def test_good_ai_would_pass_the_rule() -> None:
    """With a 95%-accurate AI the veto removes instrument-step false verdicts (~3 min)."""
    _, s = run_ablation(SimulatedOracle(accuracy=0.95), n_per_scenario=60)
    assert s["variants"]["veto"]["false_rate"] < s["v1"]["false_rate"]
    assert s["variants"]["veto"]["p_false"] < 0.05


def test_reviews_can_veto_acceptance() -> None:
    from earthtrend.analytics.ablation.review import ReviewLabel, summarize_reviews

    s = _summary(0.10, 0.80, 0.02, 0.79)
    bad = summarize_reviews(
        [ReviewLabel(case_key=f"c{i}", outcome="statistics_right") for i in range(20)]
    )
    d = decide_v2(s, "m1:1.0", reviews=bad)
    assert d.status == "reject" and d.reasons == ["reviews_do_not_support_ai"]
    good = summarize_reviews([ReviewLabel(case_key=f"c{i}", outcome="ai_right") for i in range(20)])
    assert decide_v2(s, "m1:1.0", reviews=good).status == "accept"
