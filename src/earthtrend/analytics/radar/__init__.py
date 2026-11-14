"""Radar of trends (docs/PLAN_ANALYTICS.md section 9, stage A8)."""

from earthtrend.analytics.radar.feeds import build_feeds
from earthtrend.analytics.radar.models import (
    FEED_NAMES,
    AiDetective,
    RadarCandidate,
    RadarEntry,
    RadarFeeds,
    RadarOptions,
    RadarRun,
    RadarSeries,
    TypologyCluster,
    TypologyResult,
    radar_key,
)
from earthtrend.analytics.radar.scan import run_radar, scan_stage1, scan_stage2, select_top
from earthtrend.analytics.radar.scoring import apply_novelty, score_entries
from earthtrend.analytics.radar.typology import change_typology, typology_from_candidates

__all__ = [
    "FEED_NAMES",
    "AiDetective",
    "RadarCandidate",
    "RadarEntry",
    "RadarFeeds",
    "RadarOptions",
    "RadarRun",
    "RadarSeries",
    "TypologyCluster",
    "TypologyResult",
    "apply_novelty",
    "build_feeds",
    "change_typology",
    "radar_key",
    "run_radar",
    "scan_stage1",
    "scan_stage2",
    "score_entries",
    "select_top",
    "typology_from_candidates",
]
