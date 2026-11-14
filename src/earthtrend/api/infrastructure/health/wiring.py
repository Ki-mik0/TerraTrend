"""Wire the health check from the environment and the shared cache, storage and products."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version

from earthtrend.api.application.health.service import HealthCheck
from earthtrend.api.infrastructure.health.probes import (
    AnalyticsProbe,
    CacheProbe,
    DatabaseProbe,
    ModelsProbe,
    StorageProbe,
    models_root,
)


def app_version() -> str:
    try:
        return version("earthtrend")
    except PackageNotFoundError:
        return "0.0.0+local"


def health_from_env(
    *,
    cache_ping: Callable[[], Awaitable[bool]],
    storage_ping: Callable[[], Awaitable[bool]],
    product_versions: dict[str, Callable[[], Awaitable[str]]],
) -> HealthCheck:
    db_url = os.environ.get("DB_URL", "")
    if not db_url.startswith("postgresql"):
        db_url = ""
    backend = "redis" if os.environ.get("REDIS_URL") else "memory"
    return HealthCheck(
        probes=[
            DatabaseProbe(db_url),
            StorageProbe(storage_ping),
            CacheProbe(cache_ping, backend=backend),
            AnalyticsProbe(product_versions),
            ModelsProbe(models_root()),
        ],
        version=app_version(),
    )
