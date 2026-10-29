"""Every error leaves the service as an RFC 9457 ``application/problem+json`` document."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from huron.pkg.errors import INTERNAL, NOT_FOUND, REQUEST_INVALID, HuronError, error_codes

__all__ = ["PROBLEM_MEDIA_TYPE", "install_problem_handlers", "problem_response"]

PROBLEM_MEDIA_TYPE = "application/problem+json"

_log = structlog.get_logger()


def problem_response(error: HuronError, request: Request) -> JSONResponse:
    """The response for a Huron error."""
    return JSONResponse(
        error.problem(request.url.path), status_code=error.status, media_type=PROBLEM_MEDIA_TYPE
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Register the handlers that turn every failure into a problem document."""
    app.add_exception_handler(HuronError, _huron)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _unexpected)


async def _huron(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HuronError)
    return problem_response(error, request)


async def _validation(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    problems = [
        {
            "path": "/" + "/".join(str(part) for part in item.get("loc", ())),
            "message": str(item.get("msg", "")),
            "rule": str(item.get("type", "")),
        }
        for item in error.errors()
    ]
    return _document(request, REQUEST_INVALID.code, "request is invalid", {"problems": problems})


async def _http(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    known = {entry.status: entry.code for entry in error_codes().all()}
    code = NOT_FOUND.code if error.status_code == 404 else known.get(error.status_code, "HTTP")
    return _document(request, code, str(error.detail), {}, status=error.status_code)


async def _unexpected(request: Request, error: Exception) -> JSONResponse:
    request_id = str(uuid.uuid4())
    _log.error("api.unexpected_error", request_id=request_id, error=repr(error))
    return _document(request, INTERNAL.code, "internal error", {"request_id": request_id})


def _document(
    request: Request,
    code: str,
    detail: str,
    context: dict[str, Any],
    status: int | None = None,
) -> JSONResponse:
    entry = error_codes().get(code) if code in error_codes() else None
    status_code = status or (entry.status if entry else 500)
    body = {
        "type": "https://huron.dev/problems/" + code.lower().replace("_", "-"),
        "title": entry.title if entry else "Error",
        "status": status_code,
        "detail": detail,
        "code": code,
        "context": context,
        "instance": request.url.path,
    }
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_MEDIA_TYPE)
