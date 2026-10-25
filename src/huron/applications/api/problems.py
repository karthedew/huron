"""One error shape for the whole service, and the handlers that produce it.

``install_error_handlers`` registers seven handlers, and the last is
registered for ``Exception``: every request that does not return a response
leaves through one of them, so there is no status at or above 400 that
answers in a shape other than ``application/problem+json``.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect

from huron.core.foundation.errors import ERROR_CODES as FOUNDATION_ERROR_CODES
from huron.core.foundation.errors import AuthError, DomainError
from huron.core.hierarchy.errors import ERROR_CODES as HIERARCHY_ERROR_CODES
from huron.core.security.errors import ERROR_CODES as SECURITY_ERROR_CODES
from huron.core.security.roles import RoleError

from .errors import ERROR_CODES as TRANSPORT_ERROR_CODES

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

#: Codes the framework produces that belong to no exception class: derived
#: from the status so a status the router starts answering cannot arrive
#: without a code. 404 and 405 are the two Starlette's router raises; 400 is
#: FastAPI's own body-reading exception, raised inside a matched route when
#: the request body cannot be read (for example, a client disconnect); 416
#: is ``FileResponse`` answering an unsatisfiable ``Range`` itself, with an
#: empty body and ``Content-Range``, never a problem document.
FRAMEWORK_STATUSES = (400, 404, 405, 416)

#: Raised by no class either: FastAPI's own body/query/path validation, and
#: the outermost handler.
VALIDATION_CODE = "REQUEST_INVALID"
INTERNAL_CODE = "INTERNAL_ERROR"


class Problem(BaseModel):
    """The body of every response at or above 400 (RFC 9457).

    ``type``, ``title``, ``status`` and ``detail`` are the standard problem
    members; ``code`` is the stable identifier a client switches on, from
    which ``type`` (``urn:huron:error:<code>``) and ``title`` are derived,
    and ``context`` carries structured detail such as validation errors or
    failed readiness checks when there is any. The class exists for the
    OpenAPI document - every error response ``$ref``s it - rather than for
    construction: handlers build the body directly.
    """

    type: str
    title: str
    status: int
    code: str
    detail: str
    context: dict[str, object] | None = None


def problem(status: int, code: str, detail: str, **context: object) -> JSONResponse:
    """Build a problem+json response from a status, a code and a detail.

    ``type`` and ``title`` are derived from ``code`` the same way
    ``DomainError.as_problem`` derives them, so a framework-produced
    problem and a domain one are indistinguishable in shape.

    Args:
        status: The HTTP status to answer with.
        code: The stable ``UPPER_SNAKE`` error code the client switches on.
        detail: The human-readable explanation of this occurrence.
        **context: Structured detail to publish under ``context``; omitted
            from the body entirely when empty.

    Returns:
        A response carrying the body under ``application/problem+json``.
    """
    body: dict[str, object] = {
        "type": f"urn:huron:error:{code.lower()}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "code": code,
        "detail": detail,
    }
    if context:
        body["context"] = context
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_MEDIA_TYPE)


def _problem_headers(exc: DomainError) -> dict[str, str] | None:
    """Return the response headers a domain error's class declares.

    Args:
        exc: The typed failure being answered.

    Returns:
        ``Retry-After`` carrying the class's delay in seconds, or None when
        the class declares no delay.
    """
    if exc.retry_after is None:
        return None
    return {"Retry-After": str(exc.retry_after)}


def install_error_handlers(app: FastAPI) -> None:
    """Register the seven handlers that keep every failure in the problem shape.

    Typed failures map to their own status: a ``DomainError`` to the status
    it declares (with ``Retry-After`` when its class declares a delay), an
    ``AuthError`` to 401, a ``RoleError`` to 422. The
    framework's own failures are covered too - Starlette's HTTP exceptions
    keep their status and headers, FastAPI's request validation answers 422
    with the validation errors attached, a client disconnecting mid-body
    answers 400 without touching whatever the route was writing - and the
    ``Exception`` handler catches everything else as a 500 that logs the
    traceback and puts nothing about it on the wire.

    Args:
        app: The application to register the handlers on.
    """

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        """Answer with the status, body and retry delay the domain error itself declares.

        Args:
            _request: The failing request; unused, the error is
                self-describing.
            exc: The typed failure, whose ``as_problem`` renders the body.

        Returns:
            The error's own status with its problem body, carrying
            ``Retry-After`` when the error's class declares a delay.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.as_problem(),
            media_type=PROBLEM_MEDIA_TYPE,
            headers=_problem_headers(exc),
        )

    @app.exception_handler(AuthError)
    async def auth_error(_request: Request, exc: AuthError) -> JSONResponse:
        """Answer 401 with the credential failure's code and a challenge.

        Args:
            _request: The failing request; unused.
            exc: The resolver's refusal, whose ``code`` says which kind of
                credential failed and how.

        Returns:
            A 401 carrying ``WWW-Authenticate: Bearer``, so a client that
            sent nothing learns which scheme the service accepts.
        """
        response = problem(401, exc.code, str(exc))
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RoleError)
    async def role_error(_request: Request, exc: RoleError) -> JSONResponse:
        """Answer 422 for a binding request the role model rejects.

        Args:
            _request: The failing request; unused.
            exc: The role-model refusal (an unknown role, a principal kind
                it may not be granted to, a scope it cannot bind at).

        Returns:
            A 422 with the refusal's stable code.
        """
        return problem(422, exc.code, str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Reshape a framework HTTP exception into the problem body.

        The status is kept and named as the code (``NOT_FOUND``,
        ``METHOD_NOT_ALLOWED``), and any headers the exception carries -
        ``Allow`` on a 405, for one - travel with the response.

        Args:
            _request: The failing request; unused.
            exc: The exception Starlette's router or FastAPI raised.

        Returns:
            The same status, with the problem body and the exception's
            headers.
        """
        response = problem(exc.status_code, HTTPStatus(exc.status_code).name, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Answer 422 ``REQUEST_INVALID`` with every validation error attached.

        Args:
            _request: The failing request; unused.
            exc: FastAPI's body, query or path validation failure.

        Returns:
            A 422 whose ``context.errors`` lists each violation in
            pydantic's location/message form.
        """
        return problem(
            422,
            VALIDATION_CODE,
            "the request did not satisfy the declared schema",
            errors=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(ClientDisconnect)
    async def client_disconnect(_request: Request, _exc: ClientDisconnect) -> JSONResponse:
        """Answer 400 when the client disconnects before a request body finishes.

        Raised only mid-stream, after every check that can refuse a
        request has already passed, so nothing this handler needs to
        report was ever left half-applied: a partially written upload
        part simply keeps its planned range available for the client's
        re-send.

        Args:
            _request: The failing request; unused.
            _exc: Starlette's own signal that the connection dropped;
                carries no message of its own.

        Returns:
            A 400 with the framework's own ``BAD_REQUEST`` code.
        """
        return problem(400, "BAD_REQUEST", "the client disconnected before the request completed")

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Answer 500 for anything no other handler claimed, logging it.

        The traceback goes to the log and nothing else: the body names the
        stable ``INTERNAL_ERROR`` code and a fixed detail, so an internal
        failure never leaks a message, a path or a type to the client.

        Args:
            _request: The failing request; unused.
            exc: The uncaught exception; it is logged from the active
                exception context rather than read here.

        Returns:
            A 500 with the fixed internal-error body.
        """
        logger.exception("unhandled error serving the request")
        return problem(500, INTERNAL_CODE, "the request could not be completed")


def wire_error_codes() -> frozenset[str]:
    """Collect every code this service can put on the wire.

    Compose published domain vocabularies with transport-owned failures.
    Independent tests compare these declarations with raise sites and the
    documented error contract, including parameterized path and reserved codes.

    Returns:
        The stable codes, as a set; the same code declared in two places
        counts once.
    """
    codes = {HTTPStatus(status).name for status in FRAMEWORK_STATUSES}
    codes.update({VALIDATION_CODE, INTERNAL_CODE})
    for vocabulary in (
        FOUNDATION_ERROR_CODES,
        HIERARCHY_ERROR_CODES,
        SECURITY_ERROR_CODES,
        TRANSPORT_ERROR_CODES,
    ):
        codes.update(vocabulary)
    return frozenset(codes)


PROBLEM_SCHEMA = {"$ref": "#/components/schemas/Problem"}


def problem_response(description: str) -> dict[str, object]:
    """Declare one problem+json error response for a ``responses=`` entry.

    Every declared error response goes through here so that all of them
    ``$ref`` the single shared ``Problem`` schema rather than an inline
    copy, which is what keeps the OpenAPI document's error shape uniform.

    Args:
        description: The caller-facing sentence the document shows for this
            status - what condition produces it, not how.

    Returns:
        The OpenAPI response object: the description plus a single
        ``application/problem+json`` content entry referencing ``Problem``.
    """
    return {
        "description": description,
        "content": {PROBLEM_MEDIA_TYPE: {"schema": PROBLEM_SCHEMA}},
    }


#: Every operation can answer these three, so they are declared once, on the
#: routers, and never repeated on an operation.
UNIVERSAL_ERRORS: dict[int | str, dict[str, object]] = {
    422: problem_response("the request did not satisfy the declared schema"),
    500: problem_response("an unhandled failure"),
}

#: Adds what a credential-requiring surface can answer.
AUTHENTICATED_ERRORS: dict[int | str, dict[str, object]] = {
    **UNIVERSAL_ERRORS,
    401: problem_response("no usable credential"),
    403: problem_response("the principal's role bindings do not allow this"),
}

__all__ = [
    "AUTHENTICATED_ERRORS",
    "FRAMEWORK_STATUSES",
    "INTERNAL_CODE",
    "PROBLEM_MEDIA_TYPE",
    "PROBLEM_SCHEMA",
    "UNIVERSAL_ERRORS",
    "VALIDATION_CODE",
    "Problem",
    "install_error_handlers",
    "problem",
    "problem_response",
    "wire_error_codes",
]
