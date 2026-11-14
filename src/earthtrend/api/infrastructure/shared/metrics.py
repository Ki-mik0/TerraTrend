"""Process metrics in the default Prometheus registry, served at `/metrics`."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

CACHE_HITS = Counter("cache_hits_total", "Cache reads that found a value", ["family"])
CACHE_MISSES = Counter("cache_misses_total", "Cache reads that found nothing", ["family"])
CACHE_ERRORS = Counter("cache_errors_total", "Cache calls that failed and fell back to the source", ["family"])
TILE_REQUESTS = Counter("tile_requests_total", "Map tile requests", ["product", "outcome"])
TILE_RENDER_SECONDS = Histogram("tile_render_seconds", "Time to render one PNG tile", ["product"])


def family_of(key: str) -> str:
    """The cache family is the key prefix before the first colon or slash."""
    for separator in (":", "/"):
        if separator in key:
            return key.split(separator, 1)[0]
    return "other"


def counter_value(counter: Counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()
