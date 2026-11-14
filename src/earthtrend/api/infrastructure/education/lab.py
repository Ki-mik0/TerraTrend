"""Statistics lab adapter. A synthetic series is generated and analysed in this process."""

from __future__ import annotations

from earthtrend.api.domain.education.model import LabParams, LabRun
from earthtrend.api.infrastructure.analytics_bridge import lab_series, run_blocking


class StubLab:
    async def run(self, params: LabParams) -> LabRun:
        computed = await run_blocking(
            lab_series,
            params.noise,
            params.years,
            params.autocorrelation,
            params.trend_per_decade,
            params.seed,
        )
        return LabRun(
            params=params,
            status="ready",
            slope_decade=computed["slope_decade"],
            p_value=computed["p_value"],
            n_eff=computed["n_eff"],
            significant=computed["significant"],
            series=tuple(value for value in computed["series"] if value is not None),
        )
