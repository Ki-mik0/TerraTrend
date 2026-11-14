"""Domain errors: a stable machine code plus a human message.

The api layer maps each code to an HTTP status and the body ``{code, message, details}``
(docs/Plan_Backend.md section 5). No framework imports here.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base error. Subclasses fix ``code``; the message is for logs and developers."""

    code: str = "internal_error"

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.code.replace("_", " ")
        self.details: dict[str, Any] = details
        super().__init__(self.message)


class VariableNotFound(DomainError):
    code = "variable_not_found"


class RegionNotFound(DomainError):
    code = "region_not_found"


class CaseNotFound(DomainError):
    code = "case_not_found"


class PeriodTooShort(DomainError):
    code = "period_too_short"


class InvalidSeries(DomainError):
    """The series cannot be analysed as given (empty, wrong period, malformed)."""

    code = "invalid_series"


class DataNotReady(DomainError):
    code = "data_not_ready"


class AnalyticsTimeout(DomainError):
    code = "analytics_timeout"


class AnalyticsFailed(DomainError):
    """Analytics raised; the original exception is logged, never sent to the client."""

    code = "internal_error"
