"""``HealthCheck``: liveness and readiness of the process and its dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Literal

from earthtrend.api.application.shared.analytics_port import AnalyticsPort
from earthtrend.api.application.shared.database_probe import DatabaseProbe

Kind = Literal["live", "ready", "full"]


@dataclass(frozen=True)
class HealthReport:
    status: Literal["ok", "degraded"]
    version: str
    analytics_version: str
    checks: dict[str, bool] = field(default_factory=dict)


class HealthCheck:
    def __init__(
        self,
        app_version: str,
        analytics: AnalyticsPort,
        database: DatabaseProbe,
        probe_timeout_s: float = 2.0,
    ) -> None:
        self._version = app_version
        self._analytics = analytics
        self._database = database
        self._timeout = probe_timeout_s

    async def _probe(self, check: Awaitable[bool]) -> bool:
        try:
            return bool(await asyncio.wait_for(check, self._timeout))
        except Exception:
            return False

    async def __call__(self, kind: Kind = "full") -> HealthReport:
        checks: dict[str, bool] = {}
        if kind != "live":
            db, analytics = await asyncio.gather(
                self._probe(self._database.ping()), self._probe(self._analytics.ping())
            )
            checks = {"database": db, "analytics": analytics}
        return HealthReport(
            status="ok" if all(checks.values()) else "degraded",
            version=self._version,
            analytics_version=self._analytics.version,
            checks=checks,
        )
