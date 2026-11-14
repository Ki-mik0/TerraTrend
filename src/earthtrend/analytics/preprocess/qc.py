"""Quality control of a regional series (section 4.2). Produces flag codes only."""

from __future__ import annotations

import numpy as np

from earthtrend.analytics import config
from earthtrend.analytics.models import QualityFlag
from earthtrend.analytics.preprocess.aggregate import FloatArray


def gap_share(values: FloatArray) -> float:
    return float(np.mean(~np.isfinite(values))) if values.size else 1.0


def is_constant(values: FloatArray) -> bool:
    v = values[np.isfinite(values)]
    return v.size == 0 or bool(np.nanmax(v) == np.nanmin(v))


def qc_flags(
    values: FloatArray,
    standardized: FloatArray,
    stable_fraction: float,
    years_of_data: float,
    min_years: int,
) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    share = gap_share(values)
    if share > config.MAX_GAP_SHARE:
        flags.append(QualityFlag(code="many_gaps", details={"gap_share": round(share, 4)}))
    if stable_fraction < config.LOW_STABLE_FRACTION:
        flags.append(
            QualityFlag(
                code="low_stable_coverage",
                details={"stable_fraction": round(stable_fraction, 4)},
            )
        )
    if years_of_data < min_years:
        flags.append(
            QualityFlag(
                code="short_record",
                details={"years": round(years_of_data, 2), "min_years": min_years},
            )
        )
    if is_constant(values):
        flags.append(QualityFlag(code="constant_series"))
    z = standardized[np.isfinite(standardized)]
    n_out = int(np.sum(np.abs(z) > config.OUTLIER_Z))
    if n_out:
        flags.append(QualityFlag(code="outliers", details={"count": n_out}))
    return flags
