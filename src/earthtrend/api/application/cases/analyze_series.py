"""``AnalyzeSeries``: thin-slice use case (roadmap stage 1).

A ready regional series goes to analytics in the same request and comes back as
``TrendResult`` with a verdict. Catalog checks, ``CaseSpec``, caching and persistence
join in stages B2-B4 (``CreateCase``); this use case stays the synchronous core of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from earthtrend.analytics import AnalysisOptions, RegionalSeries, TrendResult
from earthtrend.api.application.shared.analytics_port import AnalyticsPort
from earthtrend.api.domain.shared.errors import InvalidSeries


@dataclass(frozen=True)
class AnalyzeSeriesCommand:
    series: RegionalSeries
    options: AnalysisOptions


class AnalyzeSeries:
    def __init__(self, analytics: AnalyticsPort) -> None:
        self._analytics = analytics

    async def __call__(self, cmd: AnalyzeSeriesCommand) -> TrendResult:
        if not cmd.series.dates:
            raise InvalidSeries("series has no values")
        period = cmd.options.period
        if period is not None:
            first, last = cmd.series.dates[0].year, cmd.series.dates[-1].year
            if period[0] > period[1]:
                raise InvalidSeries("period start is after its end", period=list(period))
            if period[1] < first or period[0] > last:
                raise InvalidSeries(
                    "period does not overlap the series",
                    period=list(period),
                    series_years=[first, last],
                )
        return await self._analytics.analyze_series(cmd.series, cmd.options)
