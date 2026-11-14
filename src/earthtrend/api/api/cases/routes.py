"""Cases zone routes. Stage B1: ``POST /analyze`` (thin slice, synchronous)."""

from __future__ import annotations

from litestar import post
from litestar.datastructures import State
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody

from earthtrend.analytics import TrendResult
from earthtrend.api.api.cases.schemas import AnalyzeSeriesRequest
from earthtrend.api.application.cases.analyze_series import AnalyzeSeries, AnalyzeSeriesCommand


def provide_analyze_series(state: State) -> AnalyzeSeries:
    return state.analyze_series


@post(
    "/analyze",
    summary="Analyse one regional series",
    description=(
        "Runs `earthtrend.analytics.analyze_series` on the given series and returns "
        "`TrendResult` with the verdict. Synchronous; nothing is stored yet."
    ),
    status_code=200,
    tags=["cases"],
)
async def analyze(
    data: JSONBody[AnalyzeSeriesRequest], analyze_series: NamedDependency[AnalyzeSeries]
) -> TrendResult:
    return await analyze_series(AnalyzeSeriesCommand(series=data.series, options=data.options))


cases_handlers = [analyze]
cases_dependencies = {"analyze_series": Provide(provide_analyze_series, sync_to_thread=False)}
