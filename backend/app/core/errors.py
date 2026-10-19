"""Typed application errors and the consistent JSON error envelope."""
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Error raised by application code; always serialised as the error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def not_found(code: str, message: str) -> AppError:
    return AppError(code, message, status.HTTP_404_NOT_FOUND)


def unsupported(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(code, message, status.HTTP_409_CONFLICT, details)


def payload_too_large(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(code, message, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, details)


def envelope(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=envelope(exc.code, exc.message, exc.details))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=envelope("VALIDATION_ERROR", "The request payload is invalid.", safe_validation_errors(exc)),
    )


def safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return validation errors that are always JSON serialisable."""
    safe: list[dict[str, Any]] = []
    for error in exc.errors():
        safe.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": str(error.get("msg", "")),
                "input": _stringify(error.get("input")),
            }
        )
    return safe


def _stringify(value: Any) -> Any:
    if isinstance(value, (int, float, bool, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_stringify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stringify(item) for key, item in value.items()}
    return str(value)


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(f"HTTP_{exc.status_code}", str(exc.detail)),
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope("INTERNAL_ERROR", "Unexpected server error.", {"type": type(exc).__name__}),
    )
