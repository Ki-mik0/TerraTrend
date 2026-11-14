"""Embedded ``AnalyticsPort``: calls ``earthtrend.analytics`` in this process.

Analysis is CPU-bound numpy/numba work, so it runs in a worker thread to keep the event
loop free. Stage B5 swaps heavy work to a process pool behind the same port.
"""

from __future__ import annotations

import asyncio

import structlog

from earthtrend.analytics import (
    ANALYTICS_VERSION,
    AnalysisOptions,
    RegionalSeries,
    TrendResult,
    analyze_series,
)
from earthtrend.api.domain.shared.errors import AnalyticsFailed, AnalyticsTimeout, InvalidSeries

log = structlog.get_logger(__name__)


class EmbeddedAnalyticsClient:
    def __init__(self, timeout_s: float = 30.0) -> None:
        self._timeout = timeout_s

    @property
    def version(self) -> str:
        return ANALYTICS_VERSION

    async def analyze_series(self, series: RegionalSeries, options: AnalysisOptions) -> TrendResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_series, series, options), self._timeout
            )
        except TimeoutError as exc:
            raise AnalyticsTimeout(
                "analysis exceeded the time budget", timeout_s=self._timeout
            ) from exc
        except ValueError as exc:
            # Analytics validates its inputs with ValueError (incl. pydantic errors).
            raise InvalidSeries(str(exc)) from exc
        except Exception as exc:
            log.exception("analytics_failed", variable_id=series.meta.variable_id)
            raise AnalyticsFailed("analytics failed") from exc

    async def ping(self) -> bool:
        return bool(ANALYTICS_VERSION)
