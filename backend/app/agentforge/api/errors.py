"""Consistent API error responses."""

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "The request is not allowed."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "The request method is not allowed."),
    409: ("conflict", "The request conflicts with the current resource state."),
    422: ("validation_error", "Request validation failed."),
}


def error_content(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        }
    }


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code, message = _HTTP_ERROR_CODES.get(
        exc.status_code,
        ("request_error", "The request could not be processed."),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_content(code, message),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [{"code": error["type"]} for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=error_content(
            "validation_error",
            "Request validation failed.",
            details,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception while handling API request: %s",
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=error_content("internal_error", "An internal server error occurred."),
    )
