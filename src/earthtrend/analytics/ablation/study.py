"""Verdict ablation: v1 (no AI) against v2 candidates (with ``ai_expert``) on series with
known truth (docs/PLAN_ANALYTICS.md section 13.3).

Every case is analysed once; the same protocol items are then judged by v1 and by each
candidate, so the comparison is paired (McNemar). Scenarios:

* negatives (no real change): AR(1) noise at two memories, and a **sensor step** without
  a trend whose witness (another instrument) has no step - the case the AI is meant to
  catch;
* positives (real change): linear trend, accelerating trend, trend plus a sensor step.

A false verdict is ``proven``/``strong`` on a negative, or on a positive with the wrong
sign. Power is the share of positives judged ``proven``/``strong`` with the right sign.

The AI comes from an *oracle*: ``m1_oracle`` uses the active M1 model; ``SimulatedOracle``
draws opinions of a chosen accuracy from the known truth, which lets the study run (and be
tested) before M1 exists and shows how good M1 must be for v2 to pay off.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, cast

import numpy as np

from earthtrend.analytics.ablation.rules import VARIANTS, Variant, binding_items, candidate_ruleset
from earthtrend.analytics.analyze import prepare_series
from earthtrend.analytics.evidence.protocol import _ai_expert, build_protocol
from earthtrend.analytics.evidence.rules import evaluate
from earthtrend.analytics.models import AiOpinion, AnalysisOptions, RegionalSeries, TrendResult
from earthtrend.analytics.preprocess.aggregate import split_dates
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_series

TruthClass = Literal["no_trend", "linear", "step", "accelerating", "trend_plus_step"]
CLASSES: tuple[TruthClass, ...] = ("no_trend", "linear", "step", "accelerating", "trend_plus_step")
STRONG = frozenset({"proven", "strong"})


@dataclass(frozen=True)
class Scenario:
    name: str
    truth: TruthClass
    trend_per_decade: float = 0.0
    ar1: float = 0.3
    step_size: float = 0.0  # in units of noise_sd, on the main series only (instrument)
    accel: float | None = None
    n_years: int = 30
    noise_sd: float = 0.5
    witness: bool = True  # many variables have a single dataset: no witness

    @property
    def positive(self) -> bool:
        return self.truth in ("linear", "accelerating", "trend_plus_step")


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("null_ar1_0.3", "no_trend", ar1=0.3),
    Scenario("null_ar1_0.7", "no_trend", ar1=0.7),
    Scenario("sensor_step", "step", step_size=1.5),
    Scenario("linear", "linear", trend_per_decade=0.25),
    Scenario("accelerating", "accelerating", trend_per_decade=0.15, accel=0.12),
    Scenario("trend_plus_step", "trend_plus_step", trend_per_decade=0.25, step_size=1.0),
    # Single-dataset variables: v1 has no witness to expose an instrument step.
    Scenario("null_no_witness", "no_trend", ar1=0.3, witness=False),
    Scenario("sensor_step_no_witness", "step", step_size=1.5, witness=False),
    Scenario("linear_no_witness", "linear", trend_per_decade=0.25, witness=False),
)

# oracle(series, stats_significant, stats_sign, truth) -> opinion or None.
# ``truth`` exists only for simulated oracles; a real model must ignore it.
Oracle = Callable[[RegionalSeries, bool, int, TruthClass], AiOpinion | None]


def m1_oracle(models_dir: str | None = None) -> Oracle:
    """Opinions of the active M1 model (stage A6); None everywhere without a model."""

    def call(series: RegionalSeries, sig: bool, sign: int, truth: TruthClass) -> AiOpinion | None:
        del truth
        from earthtrend.analytics.ml.trendnet import ai_opinion

        p = prepare_series(series, AnalysisOptions())
        _, months = split_dates(p.dates)
        return ai_opinion(p.anom, months, sig, sign, models_dir)

    return call


@dataclass(frozen=True)
class SimulatedOracle:
    """Picks the true class with probability ``accuracy``, else a uniformly random other
    class; slope = true slope + N(0, slope_sd). Confidence is ``high`` when right with
    probability ``accuracy`` (so confidence carries some signal, like a calibrated model)."""

    accuracy: float = 0.85
    slope_sd: float = 0.05
    seed: int = 0
    true_slopes: dict[str, float] = field(default_factory=dict)

    def __call__(
        self, series: RegionalSeries, sig: bool, sign: int, truth: TruthClass
    ) -> AiOpinion | None:
        h = zlib.crc32(f"{series.meta.region_id}|{self.seed}".encode())  # stable across runs
        rng = np.random.default_rng(h)
        right = rng.random() < self.accuracy
        cls = truth if right else str(rng.choice([c for c in CLASSES if c != truth]))
        true_slope = self.true_slopes.get(series.meta.region_id, 0.0)
        slope = true_slope + float(rng.normal(0, self.slope_sd))
        if cls in ("linear", "accelerating", "trend_plus_step") and true_slope == 0.0:
            slope = abs(slope) * (sign or 1)  # a wrong "trend" call follows the data's sign
        probs = {c: (0.7 if c == cls else 0.075) for c in CLASSES}
        ai_trend = cls in ("linear", "accelerating", "trend_plus_step")
        return AiOpinion(
            model_version="simulated",
            class_probs=probs,
            predicted_class=cls,
            slope_per_decade=slope,
            slope_pi90=(slope - 1.645 * self.slope_sd, slope + 1.645 * self.slope_sd),
            confidence="high"
            if rng.random() < (self.accuracy if right else 1 - self.accuracy)
            else "medium",
            agrees_with_statistics=(ai_trend == sig)
            and (not ai_trend or math.copysign(1, slope) == sign or sign == 0),
        )


@dataclass
class CaseOutcome:
    scenario: str
    positive: bool
    true_sign: int
    v1: str
    v2: dict[str, str]
    direction: int  # sign of the v1 verdict direction (same items -> same for v2)
    ai_status: str | None
    ai_disagrees: bool


def _case_series(sc: Scenario, k: int, seed: int) -> tuple[RegionalSeries, RegionalSeries]:
    rid = f"{sc.name}#{k}"
    step_year = 1981 + sc.n_years // 2
    main = synthetic_series(
        n_years=sc.n_years,
        trend_per_decade=sc.trend_per_decade,
        noise_sd=sc.noise_sd,
        ar1=sc.ar1,
        season_amp=0.0,
        step=(step_year, sc.step_size * sc.noise_sd) if sc.step_size else None,
        accel=sc.accel,
        seed=seed * 100_003 + 2 * k,
        meta=default_meta(region_id=rid, dataset_id="main"),
    )
    witness = synthetic_series(  # independent instrument: same climate signal, no step
        n_years=sc.n_years,
        trend_per_decade=sc.trend_per_decade,
        noise_sd=sc.noise_sd,
        ar1=sc.ar1,
        season_amp=0.0,
        accel=sc.accel,
        seed=seed * 100_003 + 2 * k + 1,
        meta=default_meta(region_id=rid, dataset_id="witness"),
    )
    return main, witness


OPTS = AnalysisOptions(ai_opinion=False, nonlinear=False, seasonal_breakdown=False)


def run_case(sc: Scenario, k: int, oracle: Oracle, seed: int = 0) -> CaseOutcome:
    main, witness = _case_series(sc, k, seed)
    proto = build_protocol(main, OPTS, witnesses=[witness] if sc.witness else None)
    items = list(proto.items)
    stat = proto.item("statistics")
    mag = proto.item("magnitude")
    slope = mag.details.get("slope_per_decade") if mag is not None else None
    stats_sig = stat is not None and stat.status == "pass"
    sign = 0 if not slope else int(math.copysign(1, slope))
    op = oracle(main, stats_sig, sign, sc.truth) if stat is not None else None
    ai_status: str | None = None
    disagrees = False
    if op is not None and stat is not None:
        holder = cast(TrendResult, SimpleNamespace(ai_opinion=op, primary_slope_per_decade=slope))
        ai_item, disagrees = _ai_expert(holder, stat)
        if ai_item is not None:
            items.append(ai_item)
            ai_status = ai_item.status
    bound = binding_items(items)
    v2: dict[str, str] = {str(v): str(evaluate(bound, candidate_ruleset(v))[0]) for v in VARIANTS}
    direction = {"increasing": 1, "decreasing": -1}.get(proto.direction, 0)
    true_sign = 0 if not sc.positive else int(math.copysign(1, sc.trend_per_decade or 1))
    return CaseOutcome(
        sc.name, sc.positive, true_sign, proto.verdict, v2, direction, ai_status, disagrees
    )


def _false(o: CaseOutcome, verdict: str) -> bool:
    return verdict in STRONG and (not o.positive or o.direction != o.true_sign)


def _hit(o: CaseOutcome, verdict: str) -> bool:
    return o.positive and verdict in STRONG and o.direction == o.true_sign


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar p for discordant counts b, c."""
    from scipy.stats import binomtest

    n = b + c
    return 1.0 if n == 0 else float(binomtest(min(b, c), n, 0.5).pvalue)


def _rate(x: Sequence[bool]) -> float:
    return float(np.mean(x)) if len(x) else math.nan


def summarize(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    neg = [o for o in outcomes if not o.positive]
    pos = [o for o in outcomes if o.positive]
    out: dict[str, Any] = {
        "n_negative": len(neg),
        "n_positive": len(pos),
        "ai_coverage": _rate([o.ai_status is not None for o in outcomes]),
        "v1": {
            "false_rate": _rate([_false(o, o.v1) for o in neg + pos]),
            "false_on_negatives": _rate([_false(o, o.v1) for o in neg]),
            "false_proven": _rate([o.v1 == "proven" and _false(o, o.v1) for o in neg + pos]),
            "power": _rate([_hit(o, o.v1) for o in pos]),
        },
        "variants": {},
        "by_scenario": {},
    }
    for v in VARIANTS:
        f1 = [_false(o, o.v1) for o in neg + pos]
        f2 = [_false(o, o.v2[v]) for o in neg + pos]
        h1 = [_hit(o, o.v1) for o in pos]
        h2 = [_hit(o, o.v2[v]) for o in pos]
        out["variants"][v] = {
            "false_rate": _rate(f2),
            "false_on_negatives": _rate([_false(o, o.v2[v]) for o in neg]),
            "false_proven": _rate([o.v2[v] == "proven" and _false(o, o.v2[v]) for o in neg + pos]),
            "power": _rate(h2),
            "false_removed": int(sum(a and not b for a, b in zip(f1, f2, strict=True))),
            "false_added": int(sum(b and not a for a, b in zip(f1, f2, strict=True))),
            "hits_lost": int(sum(a and not b for a, b in zip(h1, h2, strict=True))),
            "hits_gained": int(sum(b and not a for a, b in zip(h1, h2, strict=True))),
        }
        r = out["variants"][v]
        r["p_false"] = mcnemar_p(r["false_removed"], r["false_added"])
        r["p_power"] = mcnemar_p(r["hits_lost"], r["hits_gained"])
    for name in sorted({o.scenario for o in outcomes}):
        rows = [o for o in outcomes if o.scenario == name]
        is_pos = rows[0].positive
        metric: Callable[[CaseOutcome, str], bool] = _hit if is_pos else _false
        row: dict[str, Any] = {
            "positive": is_pos,
            "n": len(rows),
            "metric": "power" if is_pos else "false_rate",
            "v1": _rate([metric(o, o.v1) for o in rows]),
        }
        for v in VARIANTS:
            row[v] = _rate([metric(o, o.v2[v]) for o in rows])
        row["ai_disagrees"] = _rate([o.ai_disagrees for o in rows])
        out["by_scenario"][name] = row
    return out


def run_ablation(
    oracle: Oracle,
    n_per_scenario: int = 200,
    scenarios: Sequence[Scenario] = DEFAULT_SCENARIOS,
    seed: int = 0,
) -> tuple[list[CaseOutcome], dict[str, Any]]:
    if isinstance(oracle, SimulatedOracle) and not oracle.true_slopes:
        slopes = {
            f"{s.name}#{k}": s.trend_per_decade for s in scenarios for k in range(n_per_scenario)
        }
        oracle = SimulatedOracle(oracle.accuracy, oracle.slope_sd, oracle.seed, slopes)
    outcomes = [run_case(sc, k, oracle, seed) for sc in scenarios for k in range(n_per_scenario)]
    return outcomes, summarize(outcomes)


__all__ = [
    "CLASSES",
    "DEFAULT_SCENARIOS",
    "CaseOutcome",
    "Oracle",
    "Scenario",
    "SimulatedOracle",
    "Variant",
    "m1_oracle",
    "mcnemar_p",
    "run_ablation",
    "run_case",
    "summarize",
]
