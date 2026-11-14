"""Health probes. A probe never raises: it reports ok, degraded, down or skipped."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

STATUSES = ("ok", "degraded", "down", "skipped")


@dataclass(frozen=True)
class ProbeResult:
    status: str
    detail: str = ""
    latency_ms: float = 0.0
    info: dict[str, str] = field(default_factory=dict)


class Probe(Protocol):
    name: str
    critical: bool

    async def check(self) -> ProbeResult: ...
