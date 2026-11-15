"""Export record. The file repeats numbers already stored on the case."""

from __future__ import annotations

from dataclasses import dataclass

FORMATS = frozenset(
    {"csv", "geojson", "ipynb", "html", "png", "pdf", "zip", "nc", "svg", "citation"}
)


class ExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def require_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise ExportError("format_invalid", "Невідомий формат експорту")
    return fmt


@dataclass
class ExportRecord:
    id: str
    case_id: str
    owner_id: str
    format: str
    status: str = "queued"
    body: bytes | None = None
    filename: str = ""

    def __post_init__(self) -> None:
        require_format(self.format)

    def mark_ready(self, body: bytes) -> None:
        self.body = body
        self.status = "ready"

    def visible_to(self, actor_id: str) -> bool:
        return self.owner_id == actor_id
