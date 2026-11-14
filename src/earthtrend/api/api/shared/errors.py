"""Map domain and framework errors to the HTTP error body ``{code, message, details}``."""

from __future__ import annotations

from typing import Any

import structlog
from litestar import MediaType, Request, Response
from litestar.exceptions import HTTPException, ValidationException
from litestar.status_codes import (
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from litestar.types import ExceptionHandlersMap

from earthtrend.api.domain.shared.errors import DomainError

log = structlog.get_logger(__name__)

STATUS_BY_CODE: dict[str, int] = {
    "variable_not_found": 404,
    "region_not_found": 404,
    "case_not_found": 404,
    "period_too_short": 422,
    "invalid_series": 422,
    "data_not_ready": 409,
    "analytics_timeout": 504,
    "internal_error": 500,
}

# Codes for errors raised by the framework itself (routing, method, body size).
CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    429: "too_many_requests",
}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def _json(status: int, body: dict[str, Any]) -> Response[dict[str, Any]]:
    return Response(content=body, status_code=status, media_type=MediaType.JSON)


def domain_error_handler(_: Request[Any, Any, Any], exc: DomainError) -> Response[dict[str, Any]]:
    status = STATUS_BY_CODE.get(exc.code, HTTP_500_INTERNAL_SERVER_ERROR)
    if status == HTTP_500_INTERNAL_SERVER_ERROR:
        # Internal details stay in the log; the client gets the code only.
        log.error("domain_error", code=exc.code, error=exc.message, details=exc.details)
        return _json(status, error_body(exc.code, "internal error"))
    return _json(status, error_body(exc.code, exc.message, exc.details))


def validation_error_handler(
    _: Request[Any, Any, Any], exc: ValidationException
) -> Response[dict[str, Any]]:
    errors = exc.extra if isinstance(exc.extra, list) else []
    return _json(
        HTTP_422_UNPROCESSABLE_ENTITY,
        error_body("invalid_request", "request validation failed", {"errors": errors}),
    )


def http_error_handler(_: Request[Any, Any, Any], exc: HTTPException) -> Response[dict[str, Any]]:
    status = exc.status_code
    code = CODE_BY_STATUS.get(status, "internal_error" if status >= 500 else "bad_request")
    message = exc.detail if status < 500 else "internal error"
    return _json(status, error_body(code, message))


def unhandled_error_handler(_: Request[Any, Any, Any], exc: Exception) -> Response[dict[str, Any]]:
    log.exception("unhandled_error", error_type=type(exc).__name__)
    return _json(HTTP_500_INTERNAL_SERVER_ERROR, error_body("internal_error", "internal error"))


def not_found_handler(_: Request[Any, Any, Any], exc: HTTPException) -> Response[dict[str, Any]]:
    return _json(HTTP_404_NOT_FOUND, error_body("not_found", exc.detail or "not found"))


EXCEPTION_HANDLERS: ExceptionHandlersMap = {
    DomainError: domain_error_handler,
    ValidationException: validation_error_handler,
    HTTPException: http_error_handler,
    HTTP_404_NOT_FOUND: not_found_handler,
    HTTP_500_INTERNAL_SERVER_ERROR: unhandled_error_handler,
    Exception: unhandled_error_handler,
}
