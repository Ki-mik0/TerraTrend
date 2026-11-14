"""Stage A11: verdict ablation (v1 vs v2 with ``ai_expert``), review of AI disagreements
and monitoring of model feedback (docs/PLAN_ANALYTICS.md sections 6.8, 11.3, 13.3)."""

from earthtrend.analytics.ablation.decision import V2Decision, decide_v2, report_markdown
from earthtrend.analytics.ablation.feedback import (
    MonitorReport,
    PredictionRecord,
    from_ai_opinion,
    from_potential,
    monitor,
)
from earthtrend.analytics.ablation.review import (
    ReviewCase,
    ReviewLabel,
    ReviewSummary,
    hard_examples,
    review_queue,
    summarize_reviews,
)
from earthtrend.analytics.ablation.rules import VARIANTS, binding_items, candidate_ruleset
from earthtrend.analytics.ablation.study import (
    DEFAULT_SCENARIOS,
    Scenario,
    SimulatedOracle,
    m1_oracle,
    run_ablation,
)

__all__ = [
    "DEFAULT_SCENARIOS",
    "VARIANTS",
    "MonitorReport",
    "PredictionRecord",
    "ReviewCase",
    "ReviewLabel",
    "ReviewSummary",
    "Scenario",
    "SimulatedOracle",
    "V2Decision",
    "binding_items",
    "candidate_ruleset",
    "decide_v2",
    "from_ai_opinion",
    "from_potential",
    "hard_examples",
    "m1_oracle",
    "monitor",
    "report_markdown",
    "review_queue",
    "run_ablation",
    "summarize_reviews",
]
