"""Monte-Carlo calibration (section 13.1): false alarms, power, verdict rates.

Every run is a pure function of (scenario, seed), so results are reproducible and the
runs can be spread over processes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.evidence.protocol import build_protocol
from earthtrend.analytics.models import AnalysisOptions, RegionalSeries, SeriesMeta
from earthtrend.analytics.preprocess.aggregate import split_dates
from earthtrend.analytics.simulate.surrogates import (
    apply_gaps,
    deseasonalize,
    iaaft_window,
    insert_step,
    insert_trend,
    skewed_ar1,
    with_witness,
)
from earthtrend.analytics.simulate.synthetic import ar1_noise, fractional_noise
from earthtrend.analytics.trend.seasonal_mk import seasonal_mk

CORE = AnalysisOptions(nonlinear=False, seasonal_breakdown=False)
Kind = Literal["ar1", "skewed", "iaaft", "witness"]


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: Kind
    phi: float = 0.5
    n_years: int = 40
    slope_per_decade: float = 0.0  # 0 = null scenario
    step: tuple[int, float] | None = None  # (index, size)
    gap_fraction: float = 0.0
    template: tuple[float, ...] | None = field(default=None, repr=False)  # for iaaft


def _meta(dataset_id: str, kind: Kind) -> SeriesMeta:
    return SeriesMeta(
        variable_id="calibration",
        concept_id="calibration",
        dataset_id=dataset_id,
        dataset_version="0",
        units="1",
        region_id="calibration",
        distribution="skewed" if kind == "skewed" else "symmetric",
    )


def _dates(n: int) -> list[date]:
    return [date(1981 + i // 12, i % 12 + 1, 1) for i in range(n)]


def synthetic_template(n: int, seed: int = 2024) -> np.ndarray:
    """Stand-in for a real anomaly series when no real data is available: AR(1) plus a
    weak long-memory component, i.e. harder than the pure AR(1) the tests assume."""
    rng = np.random.default_rng(seed)
    return ar1_noise(n, 0.5, 1.0, rng) + 0.6 * fractional_noise(n, 0.25, rng)


def make_case(sc: Scenario, seed: int) -> tuple[RegionalSeries, list[RegionalSeries]]:
    rng = np.random.default_rng(seed)
    n = sc.n_years * 12
    witnesses: list[RegionalSeries] = []
    if sc.kind == "ar1":
        x = ar1_noise(n, sc.phi, 1.0, rng)
    elif sc.kind == "skewed":
        x = skewed_ar1(n, sc.phi, rng)
    elif sc.kind == "iaaft":
        tpl = np.asarray(sc.template) if sc.template else synthetic_template(4 * n)
        anom, _ = deseasonalize(tpl)
        x = iaaft_window(anom, n, rng)
    elif sc.kind == "witness":
        x, w = with_witness(n, sc.phi, rng)
        w = insert_trend(w, sc.slope_per_decade)
        witnesses.append(
            RegionalSeries(meta=_meta("witness", sc.kind), dates=_dates(n), values=_vals(w))
        )
    else:  # pragma: no cover
        raise ValueError(sc.kind)
    x = insert_trend(x, sc.slope_per_decade)
    if sc.step:
        x = insert_step(x, *sc.step)
    if sc.gap_fraction:
        x = apply_gaps(x, rng.random(n) < sc.gap_fraction)
    primary = RegionalSeries(meta=_meta("primary", sc.kind), dates=_dates(n), values=_vals(x))
    return primary, witnesses


def _vals(x: np.ndarray) -> list[float | None]:
    return [float(v) if np.isfinite(v) else None for v in x]


# ---------------------------------------------------------------- per-run workers


def _stat(t: Any) -> float:
    return float(t.statistic) if t is not None and t.statistic is not None else 0.0


def _slope(t: Any) -> float:
    return float(t.slope_per_decade) if t is not None and t.slope_per_decade else 0.0


def _method_run(args: tuple[Scenario, int, float]) -> dict[str, Any]:
    sc, seed, alpha = args
    s, _ = make_case(sc, seed)
    r = analyze_series(s, CORE)
    ols, mk, sen = r.test("ols_ar1"), r.test("mk_ar1"), r.test("sen")
    ann = r.test("ols_ar1_annual")
    truth = sc.slope_per_decade

    def sig(t: Any) -> bool:
        return bool(t and t.p_value is not None and t.p_value < alpha)

    if sc.kind == "skewed":
        # Section 6.6: for skewed variables MK + seasonal MK decide.
        years, months = split_dates(s.dates)
        vals = np.array([np.nan if v is None else v for v in s.values])
        smk = seasonal_mk(vals, months)
        decision = (
            sig(mk) and smk is not None and smk[0] < alpha and np.sign(smk[1]) == np.sign(_stat(mk))
        )
    else:
        # Same rule as the statistics item: annual OLS at alpha, MK confirms at MK_CONFIRM_P.
        primary = ann if ann is not None and ann.p_value is not None else ols
        decision = (
            sig(primary)
            and mk is not None
            and mk.p_value is not None
            and mk.p_value < config.MK_CONFIRM_P
            and np.sign(_slope(primary)) == np.sign(_stat(mk))
        )
    return {
        "decision": bool(decision),
        "ols": sig(ols),
        "ols_annual": sig(ann),
        "mk": sig(mk),
        "sen_cover": bool(sen and sen.ci95 and sen.ci95[0] <= truth <= sen.ci95[1]),
        "ols_cover": bool(ols and ols.ci95 and ols.ci95[0] <= truth <= ols.ci95[1]),
    }


def _verdict_run(args: tuple[Scenario, int]) -> str:
    sc, seed = args
    s, w = make_case(sc, seed)
    return build_protocol(s, CORE, witnesses=w).verdict


def _parallel(fn: Callable[[Any], Any], jobs: Iterable[Any], workers: int) -> list[Any]:
    jobs = list(jobs)
    if workers <= 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, jobs, chunksize=max(1, len(jobs) // (workers * 8))))


# ---------------------------------------------------------------- public harness


def method_rates(
    sc: Scenario, runs: int, seed0: int = 0, alpha: float = 0.05, workers: int = 1
) -> dict[str, float]:
    """Rejection rates (= false alarms for a null scenario) and CI coverage."""
    res = _parallel(_method_run, [(sc, seed0 + i, alpha) for i in range(runs)], workers)
    return {k: float(np.mean([r[k] for r in res])) for k in res[0]}


def verdict_rates(sc: Scenario, runs: int, seed0: int = 0, workers: int = 1) -> dict[str, float]:
    res = _parallel(_verdict_run, [(sc, seed0 + i) for i in range(runs)], workers)
    counts = Counter(res)
    return {
        k: counts.get(k, 0) / runs
        for k in ("proven", "strong", "likely", "suspicious", "no_evidence", "inadmissible")
    }


def weatherhead_slope(n_years: float, phi: float, sigma_innov: float = 1.0) -> float:
    """Slope (per year) whose Weatherhead n* equals ``n_years`` for monthly AR(1) noise."""
    sigma_n = sigma_innov / np.sqrt(1 - phi**2)
    return float(3.3 * sigma_n * np.sqrt((1 + phi) / (1 - phi)) / n_years**1.5)


def power_curve(
    phi: float,
    n_years: int,
    multipliers: Iterable[float],
    runs: int,
    seed0: int = 0,
    workers: int = 1,
) -> list[dict[str, float]]:
    """Detection rate (both tests significant, right sign) vs slope, as multiples of the
    Weatherhead slope: at multiplier 1 the formula promises ~90% detection."""
    base = weatherhead_slope(n_years, phi) * 10  # per decade
    out = []
    for m in multipliers:
        sc = Scenario(
            name=f"power_{m}", kind="ar1", phi=phi, n_years=n_years, slope_per_decade=base * m
        )
        r = method_rates(sc, runs, seed0, workers=workers)
        out.append(
            {
                "multiplier": float(m),
                "slope_per_decade": float(base * m),
                "detect_decision": r["decision"],
                "detect_ols": r["ols"],
                "detect_mk": r["mk"],
            }
        )
    return out
