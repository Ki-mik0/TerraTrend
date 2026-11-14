# ruff: noqa: E501  (markdown table rows)
"""Decision on ``verdict_rules_v2`` from the ablation (docs/PLAN_ANALYTICS.md 6.8, 13.3).

A candidate is accepted only when, on the same cases (paired):

1. it has **fewer false** ``proven``/``strong`` verdicts, significantly (exact McNemar,
   p < ``alpha``), and adds none it did not remove more of;
2. its **power is not lower** beyond ``power_tolerance`` (2 percentage points, the same
   margin as the M1 power gate in 11.2) and the loss is not significant (McNemar);
3. the AI actually gave opinions (coverage >= ``min_ai_coverage``) and the opinions come from
   a real model, not the simulated oracle;
4. when human reviews of ``ai_disagrees`` cases exist (``review.summarize_reviews``), the AI
   is right in most of them: the lower Wilson bound of its precision is above 0.5.

Among accepted candidates the one with the lowest false rate wins (ties: higher power).
Without a real model the result is ``not_evaluated``: v1 stays.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from earthtrend.analytics.ablation.review import ReviewSummary
from earthtrend.analytics.ablation.rules import VARIANTS

ALPHA = 0.05
POWER_TOLERANCE = 0.02
MIN_AI_COVERAGE = 0.5
MIN_REVIEW_PRECISION_LOW = 0.5


class VariantCheck(BaseModel):
    variant: str
    accepted: bool
    reasons: list[str]  # codes: fewer_false_significant, power_drop_too_large, ...
    false_rate: float
    power: float
    power_drop: float
    p_false: float
    p_power: float


class V2Decision(BaseModel):
    status: Literal["accept", "reject", "not_evaluated"]
    chosen: str | None  # ruleset name, e.g. verdict_rules_v2_veto
    oracle: str  # "m1:<version>" or "simulated(accuracy=..)"
    reasons: list[str]
    v1_false_rate: float
    v1_power: float
    checks: list[VariantCheck]


def _check(
    v: str, r: dict[str, Any], v1: dict[str, float], alpha: float, tol: float
) -> VariantCheck:
    reasons: list[str] = []
    drop = v1["power"] - r["power"]
    fewer = r["false_rate"] < v1["false_rate"] and r["p_false"] < alpha
    reasons.append("fewer_false_significant" if fewer else "false_not_reduced")
    if r["false_added"] > 0:
        reasons.append("adds_false_verdicts")
    if drop > tol:
        reasons.append("power_drop_too_large")
    if r["hits_lost"] > r["hits_gained"] and r["p_power"] < alpha:
        reasons.append("power_loss_significant")
    ok = fewer and drop <= tol and not (r["hits_lost"] > r["hits_gained"] and r["p_power"] < alpha)
    if ok:
        reasons.append("power_kept")
    return VariantCheck(
        variant=v,
        accepted=ok,
        reasons=reasons,
        false_rate=r["false_rate"],
        power=r["power"],
        power_drop=drop,
        p_false=r["p_false"],
        p_power=r["p_power"],
    )


def decide_v2(
    summary: dict[str, Any],
    oracle: str,
    *,
    alpha: float = ALPHA,
    power_tolerance: float = POWER_TOLERANCE,
    min_ai_coverage: float = MIN_AI_COVERAGE,
    reviews: ReviewSummary | None = None,
) -> V2Decision:
    v1 = summary["v1"]
    checks = [_check(v, summary["variants"][v], v1, alpha, power_tolerance) for v in VARIANTS]
    base = {"v1_false_rate": v1["false_rate"], "v1_power": v1["power"], "checks": checks}
    if summary.get("ai_coverage", 0.0) < min_ai_coverage:
        return V2Decision(
            status="not_evaluated", chosen=None, oracle=oracle, reasons=["no_ai_opinions"], **base
        )
    if oracle.startswith("simulated"):
        return V2Decision(
            status="not_evaluated",
            chosen=None,
            oracle=oracle,
            reasons=["simulated_oracle_planning_only"],
            **base,
        )
    accepted = [c for c in checks if c.accepted]
    ci = reviews.ai_precision_ci95 if reviews is not None else None
    if accepted and ci is not None and ci[0] <= MIN_REVIEW_PRECISION_LOW:
        return V2Decision(
            status="reject",
            chosen=None,
            oracle=oracle,
            reasons=["reviews_do_not_support_ai"],
            **base,
        )
    if not accepted:
        return V2Decision(
            status="reject", chosen=None, oracle=oracle, reasons=["no_candidate_passed"], **base
        )
    best = min(accepted, key=lambda c: (c.false_rate, -c.power))
    return V2Decision(
        status="accept",
        chosen=f"verdict_rules_v2_{best.variant}",
        oracle=oracle,
        reasons=best.reasons,
        **base,
    )


def would_accept(summary: dict[str, Any], **kw: Any) -> bool:
    """Planning helper: would the rule accept these numbers if they came from a real model?"""
    return decide_v2(summary, "m1:hypothetical", **kw).status == "accept"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def report_markdown(
    decision: V2Decision,
    summary: dict[str, Any],
    sweep: list[dict[str, Any]] | None = None,
    n_per_scenario: int | None = None,
) -> str:
    lines = [
        "# Verdict ablation - v1 against v2 candidates with `ai_expert`",
        "",
        f"Oracle: `{decision.oracle}`"
        + (f" · {n_per_scenario} cases per scenario" if n_per_scenario else ""),
        "",
        f"**Decision: {decision.status.upper()}**"
        + (f" → `{decision.chosen}`" if decision.chosen else " → `verdict_rules_v1` stays")
        + f" ({', '.join(decision.reasons)})",
        "",
        "False = `proven`/`strong` on a case without a real change (or with the wrong sign).",
        "Power = `proven`/`strong` with the right sign on a real change.",
        "",
        "| Ruleset | false | false on negatives | power | removed / added false | hits lost | p (false) | p (power) | accepted |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| v1 | {_pct(summary['v1']['false_rate'])} | {_pct(summary['v1']['false_on_negatives'])} | "
        f"{_pct(summary['v1']['power'])} | – | – | – | – | – |",
    ]
    for c in decision.checks:
        r = summary["variants"][c.variant]
        lines.append(
            f"| v2 {c.variant} | {_pct(c.false_rate)} | {_pct(r['false_on_negatives'])} | {_pct(c.power)} | "
            f"{r['false_removed']} / {r['false_added']} | {r['hits_lost']} | {c.p_false:.2g} | "
            f"{c.p_power:.2g} | {'yes' if c.accepted else 'no'} ({', '.join(c.reasons)}) |"
        )
    lines += [
        "",
        "## By scenario",
        "",
        "| Scenario | metric | v1 | " + " | ".join(VARIANTS) + " | AI disagrees |",
    ]
    lines.append("|---|---|---|" + "---|" * len(VARIANTS) + "---|")
    for name, s in summary["by_scenario"].items():
        lines.append(
            f"| {name} | {s['metric']} | {_pct(s['v1'])} | "
            + " | ".join(_pct(s[v]) for v in VARIANTS)
            + f" | {_pct(s['ai_disagrees'])} |"
        )
    if sweep:
        lines += [
            "",
            "## How good must M1 be? (simulated oracle, planning only)",
            "",
            "| AI accuracy | v1 false | best v2 false | v1 power | best v2 power | would pass the rule |",
            "|---|---|---|---|---|---|",
        ]
        for row in sweep:
            lines.append(
                f"| {row['accuracy']:.2f} | {_pct(row['v1_false'])} | {_pct(row['v2_false'])} | "
                f"{_pct(row['v1_power'])} | {_pct(row['v2_power'])} | {'yes' if row['would_accept'] else 'no'} |"
            )
    lines += [
        "",
        "Rule (section 13.3): accept only with significantly fewer false verdicts (paired exact",
        f"McNemar, p < {ALPHA}) and power not lower by more than {POWER_TOLERANCE * 100:.0f} percentage",
        "points, with opinions from a real model. Re-run after every M1 version.",
    ]
    return "\n".join(lines) + "\n"
