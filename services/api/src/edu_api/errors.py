"""One error shape for every failure the API returns.

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": [...]}}

``code`` is a stable machine-readable string the mobile app can switch on.
``message`` is for developers and is never built from secrets or raw SQL errors.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("edu_api.errors")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """Raise anywhere in request handling to return a clean error response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_payload(
    code: str,
    message: str,
    request_id: str | None,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = ErrorBody(code=code, message=message, request_id=request_id, details=details)
    return {"error": body.model_dump(exclude_none=True)}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _json(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code, message, _request_id(request), details),
        headers=headers,
    )


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}

#: SQLSTATE classes that mean "the database is not usable right now":
#: 08 connection exception, 53 insufficient resources, 57 operator intervention
#: (includes statement timeout and shutdown).
_UNAVAILABLE_SQLSTATE_CLASSES = ("08", "53", "57")


def _is_dependency_failure(exc: DBAPIError) -> bool:
    if isinstance(exc, OperationalError | InterfaceError) or exc.connection_invalidated:
        return True
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return isinstance(sqlstate, str) and sqlstate[:2] in _UNAVAILABLE_SQLSTATE_CLASSES


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _json(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Report WHERE and WHAT, but never echo the submitted value back.
        details = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return _json(request, 422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _json(request, exc.status_code, code, message)

    async def _unavailable(request: Request, exc: Exception) -> JSONResponse:
        # Log the exception TYPE only: driver messages can contain hostnames or DSNs.
        logger.error("dependency unavailable: %s", type(exc).__name__)
        return _json(
            request,
            503,
            "dependency_unavailable",
            "A required service is temporarily unavailable. Retry later.",
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        if _is_dependency_failure(exc):
            return await _unavailable(request, exc)
        logger.error(
            "database error: %s sqlstate=%s",
            type(exc.orig).__name__,
            getattr(exc.orig, "sqlstate", None),
        )
        return _json(request, 500, "internal_error", "Unexpected server error.")

    app.add_exception_handler(PoolTimeoutError, _unavailable)
    app.add_exception_handler(ConnectionError, _unavailable)
    app.add_exception_handler(TimeoutError, _unavailable)
    app.add_exception_handler(OSError, _unavailable)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error: %s", type(exc).__name__)
        return _json(request, 500, "internal_error", "Unexpected server error.")


#: Reusable OpenAPI response declarations so every route documents the same shape.
def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    descriptions = {
        401: "Missing or invalid access token.",
        404: "Not found (or not published).",
        409: "Conflict.",
        410: "Sync cursor is no longer valid; restart pull without a cursor.",
        413: "Request body or batch too large.",
        422: "Request validation failed.",
        503: "A dependency (database or auth key service) is unavailable.",
    }
    return {
        code: {"model": ErrorResponse, "description": descriptions.get(code, "Error.")}
        for code in status_codes
    }
