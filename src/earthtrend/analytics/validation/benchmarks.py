"""Reference cases (section 13.2): cases whose correct verdict is known.

* ``SYNTHETIC`` - constructed cases covering each failure mode the protocol must catch;
  they always run.
* ``REAL`` - published results (section 13.2: fail if the sign differs or the verdict is
  weaker than ``likely``) (Arctic amplification, US NO2 decline, stratospheric
  cooling, groundwater loss in north India). They run when the Giovanni CSV fixture is
  present in ``tests/analytics/fixtures/``; otherwise they are reported as missing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from earthtrend.analytics.evidence.protocol import build_protocol
from earthtrend.analytics.models import (
    AnalysisOptions,
    ClimateIndex,
    EvidenceProtocol,
    RegionalSeries,
    SensorEvent,
    SeriesMeta,
)
from earthtrend.analytics.simulate.synthetic import ar1_noise
from earthtrend.analytics.validation.giovanni import load_giovanni_csv

N = 40 * 12
DATES = [date(1981 + i // 12, i % 12 + 1, 1) for i in range(N)]
T_DEC = np.arange(N) / 120


def _meta(dataset: str = "primary", **kw: object) -> SeriesMeta:
    data: dict[str, object] = dict(
        variable_id="bench",
        concept_id="bench",
        dataset_id=dataset,
        dataset_version="0",
        units="1",
        region_id="bench",
    )
    data.update(kw)
    return SeriesMeta.model_validate(data)


def _series(x: np.ndarray, dataset: str = "primary", **kw: object) -> RegionalSeries:
    return RegionalSeries(meta=_meta(dataset), dates=DATES, values=x.tolist(), **kw)


@dataclass(frozen=True)
class Benchmark:
    name: str
    expected: frozenset[str]  # acceptable verdicts
    must_caveat: frozenset[str]
    run: Callable[[], EvidenceProtocol]


def _steady_warming() -> EvidenceProtocol:
    rng = np.random.default_rng(1)
    common = ar1_noise(N, 0.5, 0.5, rng)
    a = 0.6 * T_DEC + common + rng.normal(0, 0.2, N)
    b = 0.6 * T_DEC + common + rng.normal(0, 0.2, N)
    return build_protocol(_series(a), witnesses=[_series(b, "witness")])


def _sensor_step() -> EvidenceProtocol:
    rng = np.random.default_rng(2)
    x = ar1_noise(N, 0.4, 0.3, rng) + np.where(np.arange(N) >= 252, 0.9, 0.0)
    return build_protocol(
        _series(x),
        AnalysisOptions(changepoints=True),
        sensor_events=[SensorEvent(date=date(2002, 3, 1), code="instrument_change")],
    )


def _enso_driven() -> EvidenceProtocol:
    rng = np.random.default_rng(3)
    idx = ar1_noise(N, 0.85, 0.5, rng) + 0.6 * T_DEC  # index with its own drift
    x = 0.9 * idx + rng.normal(0, 0.3, N)
    return build_protocol(
        _series(x), indices=[ClimateIndex(name="nino34", dates=DATES, values=idx.tolist())]
    )


def _short_record() -> EvidenceProtocol:
    rng = np.random.default_rng(4)
    x = 2.0 * T_DEC[:96] + rng.normal(0, 0.3, 96)
    s = RegionalSeries(meta=_meta(), dates=DATES[:96], values=x.tolist())
    return build_protocol(s)


def _poor_coverage() -> EvidenceProtocol:
    rng = np.random.default_rng(5)
    x = 0.6 * T_DEC + ar1_noise(N, 0.5, 0.5, rng)
    return build_protocol(_series(x, stable_fraction=0.3))


def _disagreeing_witness() -> EvidenceProtocol:
    rng = np.random.default_rng(6)
    a = 0.6 * T_DEC + ar1_noise(N, 0.5, 0.5, rng)
    b = -0.3 * T_DEC + ar1_noise(N, 0.5, 0.5, rng)
    return build_protocol(_series(a), witnesses=[_series(b, "witness")])


SYNTHETIC: list[Benchmark] = [
    Benchmark("steady_warming_with_witness", frozenset({"proven"}), frozenset(), _steady_warming),
    Benchmark(
        "sensor_step_artifact",
        frozenset({"suspicious", "no_evidence", "likely"}),
        frozenset({"possible_artifact"}),
        _sensor_step,
    ),
    Benchmark(
        "trend_explained_by_enso",
        frozenset({"likely", "suspicious", "no_evidence"}),
        frozenset({"index_trend_overlap"}),
        _enso_driven,
    ),
    Benchmark(
        "short_record", frozenset({"inadmissible"}), frozenset({"short_record"}), _short_record
    ),
    Benchmark(
        "poor_stable_coverage",
        frozenset({"suspicious"}),
        frozenset({"low_stable_coverage"}),
        _poor_coverage,
    ),
    Benchmark(
        "witness_with_opposite_sign",
        frozenset({"likely", "suspicious"}),
        frozenset({"witnesses_disagree"}),
        _disagreeing_witness,
    ),
]


@dataclass(frozen=True)
class RealReference:
    name: str
    fixture: str  # file name in tests/analytics/fixtures/
    expected: frozenset[str]
    direction: str
    source: str


REAL: list[RealReference] = [
    RealReference(
        "arctic_t2m",
        "giovanni_m2tmnxslv_t2m_arctic.csv",
        frozenset({"proven", "strong", "likely"}),
        "increasing",
        "Arctic amplification (IPCC AR6 WG1 ch. 2)",
    ),
    RealReference(
        "us_no2",
        "giovanni_omno2_no2_usa.csv",
        frozenset({"proven", "strong", "likely"}),
        "decreasing",
        "US NO2 decline (OMI, Duncan et al. 2016)",
    ),
    RealReference(
        "stratosphere_t",
        "giovanni_airs_t_50hpa_global.csv",
        frozenset({"proven", "strong", "likely"}),
        "decreasing",
        "Stratospheric cooling (IPCC AR6)",
    ),
    RealReference(
        "grace_india_tws",
        "giovanni_grace_tws_north_india.csv",
        frozenset({"proven", "strong", "likely"}),
        "decreasing",
        "Groundwater depletion (Rodell et al. 2009)",
    ),
]


def run_real(ref: RealReference, fixtures: Path) -> EvidenceProtocol | None:
    path = fixtures / ref.fixture
    if not path.exists():
        return None
    dates, values = load_giovanni_csv(path)
    s = RegionalSeries(meta=_meta(ref.name), dates=dates, values=values)
    return build_protocol(s)
