"""Uniform error responses: every error body is ``{"error": "<message>"}``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    """Build a JSON error response in the contract's format."""
    return JSONResponse({"error": message}, status_code=status_code)


def _format_validation_error(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        field = ".".join(loc)
        msg = err.get("msg", "Invalid value")
        parts.append(f"{field}: {msg}" if field else msg)
    return "Invalid request: " + ("; ".join(parts) if parts else "malformed body")


def install_error_handlers(app: FastAPI) -> None:
    """Reshape FastAPI/Starlette errors (incl. 422 validation) into ``{"error": ...}``."""

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(_format_validation_error(exc), 400)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )
