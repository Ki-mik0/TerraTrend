"""HTTP DTOs of the cases zone. Analytics models are reused as the contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from earthtrend.analytics import AnalysisOptions, RegionalSeries

# 2000 years of monthly values: generous for any real record, bounds the work per request.
MAX_POINTS = 24_000


class AnalyzeSeriesRequest(BaseModel):
    """A ready regional series and analysis options; the reply is ``TrendResult``."""

    model_config = ConfigDict(extra="forbid")

    series: RegionalSeries
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="after")
    def _limit(self) -> AnalyzeSeriesRequest:
        if len(self.series.dates) > MAX_POINTS:
            raise ValueError(f"series is longer than {MAX_POINTS} points")
        return self
