"""A job is the queue record for one heavy case. Its event stream is not a separate object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CANCELLABLE = frozenset({"queued", "running"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})
STATUSES = frozenset({"queued", "running", "completed", "failed", "cancelled"})


class JobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class RetryableJobError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass
class Job:
    id: str
    case_id: str
    status: str = "queued"
    progress: int = 0
    stage: str = "queued"
    message: str = "У черзі"
    attempts: int = 0
    created_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise JobError("status_invalid", "Невідомий статус задачі")
        if not self.events:
            self._note("progress", self._snapshot())

    def claim(self) -> None:
        if self.status != "queued":
            raise JobError("not_queued", "Задача вже не в черзі")
        self.status = "running"
        self.progress = 30
        self.stage = "load"
        self.message = "Читаємо дані"
        self._note("progress", self._snapshot())

    def start(self) -> None:
        self.claim()

    def advance(self, stage: str, progress: int, message: str) -> None:
        if self.status != "running":
            raise JobError("not_running", "Етап змінює лише виконання")
        self.stage = stage
        self.progress = progress
        self.message = message
        self._note("progress", self._snapshot())

    def finish(self) -> None:
        if self.status != "running":
            raise JobError("not_running", "Завершити можна лише виконання")
        self.status = "completed"
        self.progress = 100
        self.stage = "completed"
        self.message = "Готово"
        self._note("completed", {"case_id": self.case_id, "progress": 100, "stage": "completed"})

    def requeue(self) -> None:
        if self.status != "running":
            raise JobError("not_running", "Повторити можна лише виконання")
        self.attempts += 1
        self.status = "queued"
        self.progress = 0
        self.stage = "queued"
        self.message = "Повтор"
        self._note("progress", self._snapshot())

    def fail(self, message: str) -> None:
        if self.status in TERMINAL:
            raise JobError("already_finished", "Завершену задачу не ламають")
        self.status = "failed"
        self.stage = "failed"
        self.message = message
        self._note("progress", self._snapshot())

    def cancel(self) -> None:
        if self.status not in CANCELLABLE:
            raise JobError("cancel_not_allowed", "Завершену задачу не скасовують")
        self.status = "cancelled"
        self.stage = "cancelled"
        self.message = "Скасовано"
        self._note("progress", self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "case_id": self.case_id,
        }

    def _note(self, event: str, data: dict[str, Any]) -> None:
        self.events.append({"event": event, "data": data})
