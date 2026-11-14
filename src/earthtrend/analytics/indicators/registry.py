"""Catalogue of derived indicators (section 7) and a single entry point to compute one."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from earthtrend.analytics.indicators import etccdi
from earthtrend.analytics.indicators.etccdi import FloatArray, IntArray

InputVar = Literal["tmax", "tmin", "tmean", "pr", "snow_cover", "ndvi"]


@dataclass(frozen=True)
class IndicatorInfo:
    code: str
    input: InputVar
    units: str
    needs_base: bool
    distribution: Literal["symmetric", "skewed", "zero_inflated"]
    definition: str  # short English definition; UI texts live in the catalog/frontend


INDICATORS: dict[str, IndicatorInfo] = {
    "TX90p": IndicatorInfo(
        "TX90p",
        "tmax",
        "%",
        True,
        "skewed",
        "% of days with Tmax above the base 90th percentile for the calendar day (+-5 d)",
    ),
    "FD": IndicatorInfo("FD", "tmin", "days", False, "symmetric", "days with Tmin < 0 degC"),
    "SU": IndicatorInfo("SU", "tmax", "days", False, "zero_inflated", "days with Tmax > 25 degC"),
    "Rx5day": IndicatorInfo(
        "Rx5day", "pr", "mm", False, "skewed", "maximum 5-day precipitation total in the year"
    ),
    "CDD": IndicatorInfo(
        "CDD", "pr", "days", False, "skewed", "longest run of days with precipitation < 1 mm"
    ),
    "R95pTOT": IndicatorInfo(
        "R95pTOT",
        "pr",
        "%",
        True,
        "zero_inflated",
        "% of wet-day precipitation from days above the base 95th wet-day percentile",
    ),
    "GSL": IndicatorInfo(
        "GSL",
        "tmean",
        "days",
        False,
        "symmetric",
        "growing season length (ETCCDI: 6-day spans of T > 5 degC / T < 5 degC)",
    ),
    "SNOW_DAYS": IndicatorInfo(
        "SNOW_DAYS",
        "snow_cover",
        "days",
        False,
        "symmetric",
        "days with snow cover above 50% of the cell",
    ),
}


def compute_indicator(
    code: str,
    dates: Sequence[date],
    data: FloatArray,
    *,
    base: tuple[int, int] | None = None,
    lat: FloatArray | float | None = None,
    bootstrap_in_base: bool = True,
) -> tuple[IntArray, FloatArray]:
    """Daily ``data`` (n_days, ...) -> (years, annual values (n_years, ...))."""
    info = INDICATORS.get(code)
    if info is None:
        raise KeyError(f"unknown indicator {code!r}; known: {sorted(INDICATORS)}")
    if info.needs_base and base is None:
        raise ValueError(f"{code} needs a base period")
    data = np.asarray(data, dtype=np.float64)
    funcs: dict[str, Callable[[], tuple[IntArray, FloatArray]]] = {
        "TX90p": lambda: etccdi.tx90p(dates, data, base, bootstrap_in_base),  # type: ignore[arg-type]
        "FD": lambda: etccdi.frost_days(dates, data),
        "SU": lambda: etccdi.summer_days(dates, data),
        "Rx5day": lambda: etccdi.rx5day(dates, data),
        "CDD": lambda: etccdi.cdd(dates, data),
        "R95pTOT": lambda: etccdi.r95ptot(dates, data, base),  # type: ignore[arg-type]
        "GSL": lambda: etccdi.growing_season_length(dates, data, lat),
        "SNOW_DAYS": lambda: etccdi.snow_days(dates, data),
    }
    return funcs[code]()
