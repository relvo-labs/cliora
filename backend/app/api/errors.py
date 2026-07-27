"""Stable machine error codes and safe HTTP error mapping (00-execution-plan §5).

Responses carry a stable `code`, a safe `message`, an optional non-sensitive
`details`, and the `request_id`. Stack traces, secrets, SQL, and internal paths
are never returned.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.logging import get_logger, request_id_var

_logger = get_logger("cliora.api")


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _body(code: str, message: str, details: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {"code": code, "message": message},
        "request_id": request_id_var.get(),
    }
    if details:
        payload["error"]["details"] = details
    return payload


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(SQLAlchemyTimeoutError)
    async def _handle_pool_timeout(_: Request, exc: SQLAlchemyTimeoutError) -> JSONResponse:
        """A database connection could not be checked out in time (P4-09).

        Mapped to 503 rather than 500 because it is explicitly transient and retryable —
        and counted, because this is the only place the event is observable: without
        `pool_timeout` the request would simply hang, and without the counter a
        saturated pool would look like a scattering of unexplained 500s.

        The stable code stays `INTERNAL_ERROR` (ADR 0018): a distinct code would tell an
        unauthenticated caller that the database is under pressure, which is
        operational detail they have no need for.
        """
        from app import metrics

        metrics.increment(metrics.DATABASE_POOL_TIMEOUT_TOTAL)
        _logger.warning(
            "database_pool_timeout",
            extra={"event": "database_pool_timeout", "code": "INTERNAL_ERROR"},
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body("INTERNAL_ERROR", "An internal error occurred", None),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Log the detail server-side; return an opaque, safe body to the client.
        _logger.exception("unhandled_error", extra={"event": "unhandled_error"})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("INTERNAL_ERROR", "An internal error occurred", None),
        )
