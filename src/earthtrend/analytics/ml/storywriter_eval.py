"""Evaluation of the LLM story writer on synthetic cases (docs/PLAN_ANALYTICS.md 11.5).

Team decision: M4 is not trained; the backend connects an LLM. Before switching the LLM on
(or after changing its model or prompt), run ``evaluate_llm`` with the backend's client:
the plan's gates still apply to whoever writes the text:

* >= 95% of texts pass the number check on the first try;
* 100% of final texts mention every mandatory caveat (guaranteed by the template fallback,
  reported for the LLM's own texts);
* a blind human comparison against the template on 100 cases (``not_evaluated`` here).

Facts come from synthetic cases run through the real chain (``analyze_series`` +
``build_protocol`` + related variables + patterns), with optional witnesses, a Nino 3.4
index, an advisory AI opinion and one extra caveat, so every section and caveat occurs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.ml.storywriter import LLMComplete, write_story
from earthtrend.analytics.ml.storywriter_check import LANGS, Lang
from earthtrend.analytics.ml.storywriter_template import CAVEATS
from earthtrend.analytics.models import AiOpinion, AnalysisOptions, ClimateIndex, RegionalSeries
from earthtrend.analytics.simulate.synthetic import default_meta, synthetic_series
from earthtrend.analytics.story import build_story_facts, default_process_graph, story_lens
from earthtrend.analytics.story.models import StoryFacts

FIRST_TRY_GATE = 0.95


# Main concepts with units and a typical slope scale (units per decade).
MAIN_CONCEPTS: dict[str, tuple[str, float]] = {
    "air_temperature": ("K", 0.3),
    "sea_surface_temperature": ("K", 0.2),
    "precipitation": ("mm/day", 0.1),
    "soil_moisture_surface": ("m3/m3", 0.01),
    "ndvi": ("NDVI", 0.02),
    "evapotranspiration": ("mm/day", 0.05),
    "snow_cover": ("fraction", 0.03),
    "no2": ("molec/cm2", 0.4),
    "aerosol_optical_depth": ("AOD", 0.02),
    "terrestrial_water_storage": ("cm", 1.0),
}
AI_CLASSES = ("no_trend", "linear", "step", "accelerating", "trend_plus_step")


# ---------------------------------------------------------------- synthetic facts


@dataclass
class FactsCase:
    case_id: str
    facts: StoryFacts
    meta: dict[str, Any] = field(default_factory=dict)


def _anomaly(x: RegionalSeries) -> np.ndarray:
    v = np.array([np.nan if a is None else a for a in x.values], dtype=float)
    return np.nan_to_num(v - np.nanmean(v))


def _series(
    concept: str, region: str, values: np.ndarray, dates: list[date], suffix: str = "syn"
) -> RegionalSeries:
    units = MAIN_CONCEPTS.get(concept, ("1", 0.1))[0]
    meta = default_meta(
        variable_id=f"{concept}_{suffix}",
        concept_id=concept,
        dataset_id=f"{concept}_{suffix}",
        region_id=region,
        units=units,
    )
    return RegionalSeries(
        meta=meta,
        dates=dates,
        values=[None if np.isnan(v) else float(v) for v in values],
    )


def _nino(dates: list[date], rng: np.random.Generator) -> ClimateIndex:
    n = len(dates)
    t = np.arange(n)
    x = np.sin(2 * np.pi * t / (12 * 3.7)) + 0.5 * rng.normal(size=n)
    return ClimateIndex(name="nino34", dates=dates, values=[float(v) for v in x])


def synthetic_case(i: int, seed: int = 0) -> FactsCase:
    """One synthetic Story Lens case with real analytics on top of a simulated world."""
    rng = np.random.default_rng([seed, i])
    concepts = list(MAIN_CONCEPTS)
    concept = concepts[int(rng.integers(len(concepts)))]
    units, scale = MAIN_CONCEPTS[concept]
    region = f"syn_r{i}"
    n_years = int(rng.choice([8, 15, 22, 30, 40]))
    trend = float(rng.choice([0.0, 0.5, 1.0, 2.0]) * scale * rng.choice([-1, 1]))
    noise_sd = float(scale * rng.uniform(0.8, 3.0))
    gaps = float(rng.choice([0.0, 0.0, 0.05, 0.3]))
    step = None
    if rng.random() < 0.15 and n_years >= 15:
        step = (1981 + n_years // 2, float(2 * noise_sd * rng.choice([-1, 1])))
    main = synthetic_series(
        n_years=n_years,
        trend_per_decade=trend,
        noise_sd=noise_sd,
        ar1=float(rng.choice([0.1, 0.3, 0.6])),
        season_amp=0.0,
        step=step,
        gaps=gaps,
        seed=int(rng.integers(1 << 31)),
        meta=default_meta(
            variable_id=f"{concept}_main",
            concept_id=concept,
            dataset_id=f"{concept}_main",
            region_id=region,
            units=units,
        ),
    )
    dates = main.dates
    n = len(dates)
    t_dec = (np.arange(n) + 0.5) / 120.0
    anom = _anomaly(main)
    graph = default_process_graph()
    neighbors = [p for p in graph.neighbors(concept, max_depth=2)]
    rng.shuffle(neighbors)
    candidates: list[RegionalSeries] = []
    for path in neighbors[: int(rng.integers(0, 4))]:
        coupling = float(rng.uniform(0.0, 1.0)) * path.expected_sign
        own = float(rng.normal(0, 0.5))
        vals = coupling * anom / (np.std(anom) or 1.0) + own * t_dec + rng.normal(0, 1.0, n)
        candidates.append(_series(path.concept_id, region, vals, dates))
    witnesses: list[RegionalSeries] | None = None
    if rng.random() < 0.5:
        w = anom + trend * t_dec * float(rng.choice([1.0, 1.0, 0.0, -1.0]))
        w = w + rng.normal(0, noise_sd * 0.5, n)
        witnesses = [_series(concept, region, w, dates, suffix="witness")]
    indices = [_nino(dates, rng)] if rng.random() < 0.3 else None
    opts = AnalysisOptions()
    facts = story_lens(main, candidates, graph, opts, witnesses=witnesses, indices=indices)
    meta: dict[str, Any] = {
        "concept": concept,
        "n_years": n_years,
        "trend_per_decade": trend,
        "gaps": gaps,
        "step": step is not None,
        "n_candidates": len(candidates),
        "witness": witnesses is not None,
        "enso": indices is not None,
    }
    if rng.random() < 0.3:
        facts = _with_ai_opinion(main, opts, facts, rng)
        meta["ai_opinion"] = True
    if rng.random() < 0.3:
        extra = [c for c in CAVEATS if c not in facts.caveats]
        code = extra[int(rng.integers(len(extra)))]
        facts = facts.model_copy(update={"caveats": [*facts.caveats, code]})
        meta["augmented_caveat"] = code
    return FactsCase(case_id=f"syn{seed}_{i}", facts=facts, meta=meta)


def _with_ai_opinion(
    main: RegionalSeries, opts: AnalysisOptions, facts: StoryFacts, rng: np.random.Generator
) -> StoryFacts:
    """Attach a random advisory opinion and rebuild the facts (numbers included)."""
    p = rng.dirichlet(np.ones(len(AI_CLASSES)))
    slope = float(facts.main.slope_per_decade or 0.0) + float(rng.normal(0, 0.05))
    op = AiOpinion(
        model_version="synthetic",
        class_probs={c: float(v) for c, v in zip(AI_CLASSES, p, strict=True)},
        predicted_class=AI_CLASSES[int(np.argmax(p))],
        slope_per_decade=slope,
        slope_pi90=(slope - 0.1, slope + 0.1),
        confidence=("high", "medium", "low")[int(rng.integers(3))],
        agrees_with_statistics=bool(rng.random() < 0.7),
    )
    tr = analyze_series(main, opts).model_copy(update={"ai_opinion": op})
    rebuilt = build_story_facts(tr, None, facts.related, facts.patterns, facts.graph_version)
    # keep the protocol-based main facts and caveats; take numbers of the AI opinion
    numbers = {**facts.numbers, **{k: v for k, v in rebuilt.numbers.items() if k.startswith("ai.")}}
    caveats = list(facts.caveats)
    if not op.agrees_with_statistics and "ai_disagrees" not in caveats:
        caveats.append("ai_disagrees")  # what build_protocol does for a disagreeing opinion
    return facts.model_copy(update={"ai_opinion": op, "numbers": numbers, "caveats": caveats})


def synthetic_facts(n: int, seed: int = 0) -> list[FactsCase]:
    return [synthetic_case(i, seed) for i in range(n)]


def evaluate_llm(
    llm: LLMComplete,
    n_cases: int = 50,
    langs: Sequence[Lang] = LANGS,
    seed: int = 0,
    llm_label: str = "external_llm",
) -> dict[str, Any]:
    """Run the writer with ``llm`` on synthetic cases and report the gates."""
    first_try = final_llm = caveats_ok = total = 0
    reasons: Counter[str] = Counter()
    for case in synthetic_facts(n_cases, seed):
        for lang in langs:
            total += 1
            out = write_story(case.facts, lang, llm=llm, llm_label=llm_label)
            if out.method == "llm":
                final_llm += 1
                first_try += out.attempts == 1
            else:
                reasons[out.fallback_reason or "unknown"] += 1
            caveats_ok += not out.check.missing_caveats
    rate = first_try / total if total else 0.0
    return {
        "n_texts": total,
        "first_try_pass_rate": rate,
        "llm_text_rate": final_llm / total if total else 0.0,
        "caveats_present_rate": caveats_ok / total if total else 0.0,
        "fallback_reasons": dict(reasons),
        "gates": {
            "first_try_number_check_ge_95pct": rate >= FIRST_TRY_GATE,
            "all_caveats_present": caveats_ok == total,
            "blind_human_comparison": "not_evaluated",
        },
        "status": "pass" if rate >= FIRST_TRY_GATE and caveats_ok == total else "fail",
    }
