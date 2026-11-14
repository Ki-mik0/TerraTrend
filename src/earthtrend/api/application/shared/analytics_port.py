"""``AnalyticsPort``: the only way use cases reach ``earthtrend.analytics``.

The analytics models are the contract (Plan_Backend "Контракт із сусідами"): the port
passes ``RegionalSeries`` / ``AnalysisOptions`` in and returns ``TrendResult`` untouched.
"""

from __future__ import annotations

from typing import Protocol

from earthtrend.analytics import AnalysisOptions, RegionalSeries, TrendResult


class AnalyticsPort(Protocol):
    @property
    def version(self) -> str:
        """``ANALYTICS_VERSION`` of the implementation (part of the case reproduction key)."""
        ...

    async def analyze_series(
        self, series: RegionalSeries, options: AnalysisOptions
    ) -> TrendResult: ...

    async def ping(self) -> bool:
        """True when analytics can serve requests (readiness probe)."""
        ...
