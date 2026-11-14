"""HealthCheck: live, ready and the full report.

- live: the process answers. No dependency is touched, so a slow database never kills the pod.
- ready: every critical probe is ok or skipped. Otherwise the instance should not get traffic.
- full: every probe, the app version and uptime. A failing non-critical probe only degrades.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace

from earthtrend.api.application.health.ports import Probe, ProbeResult

PROBE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class HealthReport:
    status: str  # ok, degraded or down
    version: str
    uptime_seconds: float
    checks: dict[str, ProbeResult]

    @property
    def serving(self) -> bool:
        return self.status != "down"


class HealthCheck:
    def __init__(
        self,
        *,
        probes: list[Probe],
        version: str,
        timeout: float = PROBE_TIMEOUT_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._probes = probes
        self._version = version
        self._timeout = timeout
        self._clock = clock
        self._started = clock()

    def live(self) -> HealthReport:
        return HealthReport(status="ok", version=self._version, uptime_seconds=self._uptime(), checks={})

    async def ready(self) -> HealthReport:
        return await self._run([probe for probe in self._probes if probe.critical])

    async def full(self) -> HealthReport:
        return await self._run(self._probes)

    async def _run(self, probes: list[Probe]) -> HealthReport:
        results = await asyncio.gather(*(self._check(probe) for probe in probes))
        checks = {probe.name: result for probe, result in zip(probes, results)}
        status = "ok"
        for probe, result in zip(probes, results):
            if result.status == "down" and probe.critical:
                status = "down"
                break
            if result.status in {"down", "degraded"}:
                status = "degraded"
        return HealthReport(status=status, version=self._version, uptime_seconds=self._uptime(), checks=checks)

    async def _check(self, probe: Probe) -> ProbeResult:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(probe.check(), timeout=self._timeout)
        except TimeoutError:
            result = ProbeResult(status="down", detail=f"timeout after {self._timeout:g}s")
        except Exception as error:  # a probe must never take the health route down
            result = ProbeResult(status="down", detail=type(error).__name__)
        if result.status == "down" and not probe.critical:
            result = replace(result, status="degraded")
        return replace(result, latency_ms=round((time.perf_counter() - started) * 1000, 2))

    def _uptime(self) -> float:
        return round(self._clock() - self._started, 3)
