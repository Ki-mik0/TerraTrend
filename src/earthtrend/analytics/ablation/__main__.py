"""CLI: ``python -m earthtrend.analytics.ablation [--oracle m1|simulated] ...``.

Writes ``docs/validation/ablation_v2.md`` and ``.json``. With ``--oracle m1`` and no active
M1 model the decision is ``not_evaluated`` and v1 stays.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from earthtrend.analytics.ablation.decision import decide_v2, report_markdown, would_accept
from earthtrend.analytics.ablation.rules import VARIANTS
from earthtrend.analytics.ablation.study import SimulatedOracle, m1_oracle, run_ablation

DOCS = Path(__file__).resolve().parents[4] / "docs" / "validation"


def accuracy_sweep(accuracies: list[float], n: int, seed: int) -> list[dict[str, float | bool]]:
    rows: list[dict[str, float | bool]] = []
    for acc in accuracies:
        _, s = run_ablation(SimulatedOracle(accuracy=acc, seed=seed), n_per_scenario=n, seed=seed)
        best = min(
            VARIANTS, key=lambda v: (s["variants"][v]["false_rate"], -s["variants"][v]["power"])
        )
        rows.append(
            {
                "accuracy": acc,
                "v1_false": s["v1"]["false_rate"],
                "v2_false": s["variants"][best]["false_rate"],
                "v1_power": s["v1"]["power"],
                "v2_power": s["variants"][best]["power"],
                "would_accept": would_accept(s),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="earthtrend-ablation")
    ap.add_argument("--oracle", choices=["m1", "simulated"], default="m1")
    ap.add_argument("--accuracy", type=float, default=0.85)
    ap.add_argument("--n", type=int, default=200, help="cases per scenario")
    ap.add_argument("--sweep", type=float, nargs="*", default=None, help="AI accuracies")
    ap.add_argument("--sweep-n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=DOCS)
    ap.add_argument("--models-dir", default=None)
    a = ap.parse_args(argv)

    if a.oracle == "m1":
        from earthtrend.analytics.ml.trendnet import active_version

        version = active_version(a.models_dir)
        oracle_name = f"m1:{version}" if version else "m1:none"
        oracle = m1_oracle(a.models_dir)
    else:
        oracle_name = f"simulated(accuracy={a.accuracy})"
        oracle = SimulatedOracle(accuracy=a.accuracy, seed=a.seed)
    _, summary = run_ablation(oracle, n_per_scenario=a.n, seed=a.seed)
    decision = decide_v2(summary, oracle_name)
    sweep = accuracy_sweep(a.sweep, a.sweep_n, a.seed) if a.sweep else None
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "ablation_v2.md").write_text(
        report_markdown(decision, summary, sweep, a.n), encoding="utf-8"
    )
    (a.out / "ablation_v2.json").write_text(
        json.dumps(
            {"decision": decision.model_dump(), "summary": summary, "sweep": sweep, "n": a.n},
            indent=2,
        ),
        encoding="utf-8",
    )
    chosen = decision.chosen or "verdict_rules_v1"
    print(f"{decision.status}: {chosen} ({', '.join(decision.reasons)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
