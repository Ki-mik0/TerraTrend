"""Derived climate indicators (section 7): ETCCDI-style annual indices from daily data."""

from earthtrend.analytics.indicators.annual import analyze_annual_series
from earthtrend.analytics.indicators.registry import INDICATORS, IndicatorInfo, compute_indicator

__all__ = ["INDICATORS", "IndicatorInfo", "analyze_annual_series", "compute_indicator"]
