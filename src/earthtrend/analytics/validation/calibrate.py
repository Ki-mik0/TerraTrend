"""Stage 4 calibration run: ``python -m earthtrend.analytics.validation.calibrate``.

Writes ``docs/validation/calibration_v1.json`` (+ ``.md``) and figures in ``docs/methods/``.
The JSON stores the calibration fingerprint; ``test_calibration_gate.py`` fails when the
current thresholds no longer match it.

Acceptance (ROADMAP stage 4):
* decision rule and annual OLS: false alarms within 3-7% in every null scenario;
  the single monthly tests within 3-7% on AR(1) nulls (reported, not required, under
  long memory, where they are known to over-reject - see the report);
* verdicts on nulls: false ``proven`` < 1%, false ``strong``-or-better < 5%;
* detection at the Weatherhead slope within 80-97% (the formula promises ~90%);
* all synthetic reference cases give an acceptable verdict and their caveats.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.validation.benchmarks import REAL, SYNTHETIC, run_real
from earthtrend.analytics.validation.fingerprint import calibration_fingerprint, thresholds
from earthtrend.analytics.validation.giovanni import load_giovanni_csv
from earthtrend.analytics.validation.monte_carlo import (
    Scenario,
    method_rates,
    power_curve,
    verdict_rates,
    weatherhead_slope,
)

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "tests" / "analytics" / "fixtures"
FA_RANGE = (0.03, 0.07)
MAX_FALSE_PROVEN = 0.01
MAX_FALSE_STRONG = 0.05
WEATHERHEAD_RANGE = (0.80, 0.97)


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(centre - half, 4), round(centre + half, 4)


def null_scenarios() -> list[Scenario]:
    scs = [
        Scenario("ar1_phi0.0", "ar1", 0.0),
        Scenario("ar1_phi0.3", "ar1", 0.3),
        Scenario("ar1_phi0.6", "ar1", 0.6),
        Scenario("ar1_phi0.8", "ar1", 0.8),
        Scenario("ar1_phi0.5_gaps15", "ar1", 0.5, gap_fraction=0.15),
        Scenario("skewed_gamma_phi0.4", "skewed", 0.4),
        Scenario("iaaft_synthetic_long_memory", "iaaft"),
        Scenario("witness_shared0.8_phi0.5", "witness", 0.5),
    ]
    real = FIXTURES / "giovanni_m2tmnxslv_t2m_arctic.csv"
    if real.exists():
        _, vals = load_giovanni_csv(real)
        tpl = np.array([np.nan if v is None else v for v in vals])
        n_years = len(tpl) // 24
        if n_years >= 12:
            scs.append(
                Scenario("iaaft_real_arctic_t2m", "iaaft", n_years=n_years, template=tuple(tpl))
            )
    return scs


def run(runs: int, verdict_runs: int, power_runs: int, workers: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "fingerprint": calibration_fingerprint(),
        "ruleset": "verdict_rules_v1",
        "analytics_version": config.ANALYTICS_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "runs": {"method": runs, "verdict": verdict_runs, "power": power_runs},
        "thresholds": thresholds(),
        "null_scenarios": [],
        "acceptance": {},
    }
    acc: dict[str, bool] = {}

    for i, sc in enumerate(null_scenarios()):
        print(f"[null] {sc.name}", flush=True)
        m = method_rates(sc, runs, seed0=1_000_000 * (i + 1), workers=workers)
        v = verdict_rates(sc, verdict_runs, seed0=1_000_000 * (i + 1) + 500_000, workers=workers)
        entry = {
            "scenario": {k: val for k, val in asdict(sc).items() if k != "template"},
            "false_alarm": {
                k: {"rate": m[k], "ci95": wilson(m[k], runs)}
                for k in ("decision", "ols_annual", "ols", "mk")
            },
            "verdicts": v,
        }
        report["null_scenarios"].append(entry)
        lo, hi = FA_RANGE
        acc[f"{sc.name}: decision FA in 3-7%"] = lo <= m["decision"] <= hi
        if sc.kind != "skewed":
            acc[f"{sc.name}: annual OLS FA in 3-7%"] = lo <= m["ols_annual"] <= hi
        if sc.kind == "ar1":
            acc[f"{sc.name}: monthly OLS FA in 3-7%"] = lo <= m["ols"] <= hi
            acc[f"{sc.name}: monthly MK FA in 3-7%"] = lo <= m["mk"] <= hi
        acc[f"{sc.name}: false proven < 1%"] = v["proven"] < MAX_FALSE_PROVEN
        acc[f"{sc.name}: false strong-or-better < 5%"] = (
            v["proven"] + v["strong"] < MAX_FALSE_STRONG
        )

    print("[power]", flush=True)
    mult = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    pc = power_curve(0.5, 40, mult, power_runs, seed0=90_000_000, workers=workers)
    at1 = next(p for p in pc if p["multiplier"] == 1.0)
    report["power"] = {
        "phi": 0.5,
        "n_years": 40,
        "weatherhead_slope_per_decade": weatherhead_slope(40, 0.5) * 10,
        "curve": pc,
    }
    acc["detection at Weatherhead slope in 80-97% (decision rule)"] = (
        WEATHERHEAD_RANGE[0] <= at1["detect_decision"] <= WEATHERHEAD_RANGE[1]
    )

    print("[signal verdicts]", flush=True)
    strong_sig = Scenario(
        "witness_trend_2x_weatherhead",
        "witness",
        0.5,
        slope_per_decade=2 * weatherhead_slope(40, 0.5) * 10,
    )
    report["signal_verdicts"] = {
        "scenario": asdict(strong_sig),
        "verdicts": verdict_rates(strong_sig, verdict_runs, seed0=95_000_000, workers=workers),
    }

    print("[benchmarks]", flush=True)
    bench: list[dict[str, Any]] = []
    for b in SYNTHETIC:
        pr = b.run()
        ok = pr.verdict in b.expected and b.must_caveat <= set(pr.caveats)
        bench.append(
            {
                "name": b.name,
                "verdict": pr.verdict,
                "strength": pr.strength,
                "caveats": pr.caveats,
                "expected": sorted(b.expected),
                "passed": ok,
            }
        )
        acc[f"benchmark {b.name}"] = ok
    report["benchmarks_synthetic"] = bench
    real: list[dict[str, Any]] = []
    for ref in REAL:
        res = run_real(ref, FIXTURES)
        if res is None:
            real.append({"name": ref.name, "status": "missing_fixture", "fixture": ref.fixture})
            continue
        ok = pr.verdict in ref.expected and pr.direction == ref.direction
        real.append(
            {
                "name": ref.name,
                "verdict": pr.verdict,
                "direction": pr.direction,
                "passed": ok,
                "source": ref.source,
            }
        )
        acc[f"real reference {ref.name}"] = ok
    report["benchmarks_real"] = real

    report["acceptance"] = acc
    report["passed"] = all(acc.values())
    return report


def _cell(fa: dict[str, Any], k: str) -> str:
    lo, hi = fa[k]["ci95"]
    return f"{fa[k]['rate']:.3f} ({lo:.3f}–{hi:.3f})"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Calibration report — verdict_rules_v1",
        "",
        f"Fingerprint `{report['fingerprint']}` · analytics {report['analytics_version']} · "
        f"{report['generated_utc']} · runs: {report['runs']}",
        "",
        f"**Overall: {'PASSED' if report['passed'] else 'FAILED'}**",
        "",
        "## False alarms on null scenarios (rate, 95% CI)",
        "",
        "| Scenario | decision rule | OLS annual | OLS monthly | MK monthly | proven | strong |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in report["null_scenarios"]:
        fa = e["false_alarm"]
        lines.append(
            f"| {e['scenario']['name']} | {_cell(fa, 'decision')} | {_cell(fa, 'ols_annual')} | "
            f"{_cell(fa, 'ols')} | {_cell(fa, 'mk')} | {e['verdicts']['proven']:.3f} | "
            f"{e['verdicts']['strong']:.3f} |"
        )
    lines += [
        "",
        "The decision rule is what the verdict uses: OLS with AR(1) n_eff on annual means "
        "at alpha, confirmed by Mann-Kendall (AR(1) rank correction) with the same sign at "
        "p < MK_CONFIRM_P (skewed variables: MK and seasonal MK at alpha). The monthly tests "
        "over-reject under long memory and are reported only.",
        "",
        "## Power",
        "",
        f"AR(1) φ = 0.5, 40 years; Weatherhead slope = "
        f"{report['power']['weatherhead_slope_per_decade']:.3f} per decade "
        "(formula promises ~90% detection there).",
        "",
        "| × Weatherhead slope | slope / decade | decision rule | OLS monthly | MK monthly |",
        "|---|---|---|---|---|",
    ]
    for p in report["power"]["curve"]:
        lines.append(
            f"| {p['multiplier']} | {p['slope_per_decade']:.3f} | {p['detect_decision']:.3f} | "
            f"{p['detect_ols']:.3f} | {p['detect_mk']:.3f} |"
        )
    sv = report["signal_verdicts"]["verdicts"]
    lines += [
        "",
        "## Verdicts on a real trend (2 × Weatherhead slope, with a witness)",
        "",
        " · ".join(f"{k}: {v:.3f}" for k, v in sv.items()),
        "",
        "## Reference cases",
        "",
        "| Case | verdict | expected | passed |",
        "|---|---|---|---|",
    ]
    for b in report["benchmarks_synthetic"]:
        lines.append(
            f"| {b['name']} | {b['verdict']} | {', '.join(b['expected'])} | {b['passed']} |"
        )
    for r in report["benchmarks_real"]:
        if r.get("status") == "missing_fixture":
            lines.append(f"| {r['name']} (real) | — | fixture `{r['fixture']}` missing | not run |")
        else:
            lines.append(
                f"| {r['name']} (real) | {r['verdict']} | {r['direction']} | {r['passed']} |"
            )
    lines += ["", "## Acceptance", ""]
    lines += [f"- [{'x' if ok else ' '}] {k}" for k, ok in report["acceptance"].items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_figures(report: dict[str, Any], fig_dir: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    fig_dir.mkdir(parents=True, exist_ok=True)
    out = []

    pc = report["power"]["curve"]
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = [p["multiplier"] for p in pc]
    ax.plot(xs, [p["detect_decision"] for p in pc], "o-", label="decision rule (verdict)")
    ax.plot(xs, [p["detect_ols"] for p in pc], "s--", label="OLS monthly")
    ax.plot(xs, [p["detect_mk"] for p in pc], "^--", label="MK monthly")
    ax.axhline(0.9, color="grey", lw=0.8, ls=":")
    ax.axvline(1.0, color="grey", lw=0.8, ls=":")
    ax.set_xlabel("slope / Weatherhead slope (n* = 40 years)")
    ax.set_ylabel("detection rate")
    ax.set_title("Power, AR(1) φ = 0.5, 40 years")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "power_curve.png", dpi=120)
    plt.close(fig)
    out.append("power_curve.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    names = [e["scenario"]["name"] for e in report["null_scenarios"]]
    keys = ["decision", "ols_annual", "ols", "mk"]
    w = 0.2
    for j, k in enumerate(keys):
        rates = [e["false_alarm"][k]["rate"] for e in report["null_scenarios"]]
        ax.bar(np.arange(len(names)) + (j - 1.5) * w, rates, w, label=k)
    ax.axhspan(*FA_RANGE, color="green", alpha=0.1)
    ax.axhline(0.05, color="grey", lw=0.8, ls=":")
    ax.set_xticks(np.arange(len(names)))
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("false-alarm rate")
    ax.set_title("False alarms on null scenarios (target band 3–7%)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "false_alarms.png", dpi=120)
    plt.close(fig)
    out.append("false_alarms.png")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=10_000, help="method runs per null scenario (13.1)")
    ap.add_argument("--verdict-runs", type=int, default=1000)
    ap.add_argument("--power-runs", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "validation")
    ap.add_argument("--figures", type=Path, default=ROOT / "docs" / "methods")
    args = ap.parse_args(argv)

    report = run(args.runs, args.verdict_runs, args.power_runs, args.workers)
    report["figures"] = write_figures(report, args.figures)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "calibration_v1.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    write_markdown(report, args.out / "calibration_v1.md")
    print(f"passed={report['passed']} fingerprint={report['fingerprint']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
