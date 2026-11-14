"""Quality item (section 6.5) and the checks only it needs: long memory, sensor artifacts."""

from __future__ import annotations

from datetime import date

import numpy as np
from scipy import stats

from earthtrend.analytics.models import ItemStatus, QualityFlag, SensorEvent
from earthtrend.analytics.preprocess.aggregate import FloatArray

LONG_MEMORY_LAGS = range(2, 13)
LONG_MEMORY_P = 0.01
ARTIFACT_WINDOW_MONTHS = 6
EDGE_SHARE = 0.10  # change points in the first / last 10% of the record are "edge"

FAIL_FLAGS = frozenset({"many_gaps", "low_stable_coverage", "possible_artifact"})
WARNING_FLAGS = frozenset(
    {"outliers", "low_n_eff", "long_memory", "influential_year", "possible_artifact_edge"}
)


def long_memory(resid: FloatArray) -> tuple[bool, float]:
    """Ljung-Box on AR(1)-prewhitened residuals, lags 2..12 (section 5.1, step 6).

    AR(1) structure is handled by n_eff; what is left at longer lags means the AR(1)
    correction is not enough. Returns (flag, p-value).
    """
    e = resid[np.isfinite(resid)]
    n = e.size
    if n < 36:
        return False, 1.0
    e = e - e.mean()
    r1 = float(np.dot(e[:-1], e[1:]) / np.dot(e, e))
    w = e[1:] - r1 * e[:-1]
    w = w - w.mean()
    m = w.size
    den = float(np.dot(w, w))
    if den == 0:
        return False, 1.0
    q = 0.0
    for k in LONG_MEMORY_LAGS:
        rho = float(np.dot(w[:-k], w[k:]) / den)
        q += rho * rho / (m - k)
    q *= m * (m + 2)
    p = float(stats.chi2.sf(q, df=len(LONG_MEMORY_LAGS)))
    return p < LONG_MEMORY_P, p


def _months_between(a: date, b: date) -> int:
    return abs((a.year - b.year) * 12 + a.month - b.month)


def artifact_flags(
    changepoints: list[date], events: list[SensorEvent], period: tuple[date, date] | None
) -> list[QualityFlag]:
    """A change point within 6 months of a sensor event is a possible artifact."""
    if not changepoints or not events or period is None:
        return []
    span = max(_months_between(*period), 1)
    flags: list[QualityFlag] = []
    for cp in changepoints:
        for ev in events:
            if _months_between(cp, ev.date) <= ARTIFACT_WINDOW_MONTHS:
                pos = _months_between(cp, period[0]) / span
                edge = pos < EDGE_SHARE or pos > 1 - EDGE_SHARE
                flags.append(
                    QualityFlag(
                        code="possible_artifact_edge" if edge else "possible_artifact",
                        details={"changepoint": cp.isoformat(), "event": ev.code},
                    )
                )
    return flags


def sensor_events_in_period(
    events: list[SensorEvent], period: tuple[date, date] | None
) -> list[SensorEvent]:
    if period is None:
        return []
    return [e for e in events if period[0] <= e.date <= period[1]]


def quality_status(flags: list[QualityFlag]) -> ItemStatus:
    codes = {f.code for f in flags}
    if codes & FAIL_FLAGS:
        return "fail"
    warnings = len(codes & WARNING_FLAGS)
    if warnings == 0:
        return "pass"
    return "partial" if warnings <= 2 else "fail"
