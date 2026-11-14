"""EarthTrend analytics core: public facade.

The API imports only names exported here. Analytics never downloads data or touches
HTTP, databases or files: arrays in, Pydantic models out.
"""

from earthtrend.analytics.analyze import analyze_series
from earthtrend.analytics.config import ANALYTICS_VERSION
from earthtrend.analytics.evidence.protocol import build_protocol
from earthtrend.analytics.models import (
    AiOpinion,
    AnalysisOptions,
    ClimateIndex,
    EvidenceItem,
    EvidenceProtocol,
    GridSummary,
    Magnitude,
    QualityFlag,
    RegionalSeries,
    SensorEvent,
    SeriesMeta,
    SeriesPayload,
    SplitResult,
    TrendResult,
    TrendTest,
    Verdict,
    Zone,
)
from earthtrend.analytics.radar import (
    RadarEntry,
    RadarOptions,
    RadarRun,
    RadarSeries,
    run_radar,
)
from earthtrend.analytics.regional.reduce import regional_series
from earthtrend.analytics.spatial.product import GridTrendProduct, analyze_grid
from earthtrend.analytics.story import StoryFacts, load_process_graph, story_lens

__all__ = [
    "RadarEntry",
    "RadarOptions",
    "RadarRun",
    "RadarSeries",
    "StoryFacts",
    "load_process_graph",
    "run_radar",
    "story_lens",
    "ANALYTICS_VERSION",
    "AiOpinion",
    "AnalysisOptions",
    "ClimateIndex",
    "EvidenceItem",
    "EvidenceProtocol",
    "SensorEvent",
    "build_protocol",
    "GridSummary",
    "GridTrendProduct",
    "SplitResult",
    "Zone",
    "analyze_grid",
    "Magnitude",
    "QualityFlag",
    "RegionalSeries",
    "SeriesMeta",
    "SeriesPayload",
    "TrendResult",
    "TrendTest",
    "Verdict",
    "analyze_series",
    "regional_series",
]
