"""One error shape for the whole service, and the handlers that produce it.

``install_error_handlers`` registers six handlers, and the last is
registered for ``Exception``: every request that does not return a response
leaves through one of them, so there is no status at or above 400 that
answers in a shape other than ``application/problem+json``.
"""

from __future__ import annotations

import ast
import inspect
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from huron.pkg.auth import AuthError
from huron.pkg.catalog import manifest as catalog_manifest
from huron.pkg.catalog.errors import DomainError
from huron.pkg.rbac.roles import RoleError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

#: Codes the framework produces that belong to no exception class: derived
#: from the status so a status the router starts answering cannot arrive
#: without a code. 404 and 405 are the two Starlette's router raises; 400 is
#: FastAPI's own body-reading exception, raised inside a matched route when
#: the request body cannot be read (for example, a client disconnect).
FRAMEWORK_STATUSES = (400, 404, 405)

#: Raised by no class either: FastAPI's own body/query/path validation, and
#: the outermost handler.
VALIDATION_CODE = "REQUEST_INVALID"
INTERNAL_CODE = "INTERNAL_ERROR"


class Problem(BaseModel):
    """The body of every response at or above 400 (RFC 9457)."""

    type: str
    title: str
    status: int
    code: str
    detail: str
    context: dict[str, object] | None = None


def problem(status: int, code: str, detail: str, **context: object) -> JSONResponse:
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


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.as_problem(),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(AuthError)
    async def auth_error(_request: Request, exc: AuthError) -> JSONResponse:
        response = problem(401, exc.code, str(exc))
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RoleError)
    async def role_error(_request: Request, exc: RoleError) -> JSONResponse:
        return problem(422, exc.code, str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = problem(exc.status_code, HTTPStatus(exc.status_code).name, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(
            422,
            VALIDATION_CODE,
            "the request did not satisfy the declared schema",
            errors=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error serving the request")
        return problem(500, INTERNAL_CODE, "the request could not be completed")


def _descendant_codes(base: type[Exception]) -> frozenset[str]:
    """Every stable code ``base`` or one of its subclasses declares.

    Walks ``__subclasses__()`` transitively instead of reading a list, so a
    subclass defined anywhere is included without anyone remembering to say
    so. A class that declares no ``code`` of its own - an abstract dispatch
    base like ``DomainError`` or ``RoleError`` - contributes nothing, which
    is what makes its abstractness visible to a test rather than only to a
    reader.
    """
    codes: set[str] = set()
    stack = [base]
    while stack:
        cls = stack.pop()
        code = cls.__dict__.get("code")
        if isinstance(code, str):
            codes.add(code)
        stack.extend(cls.__subclasses__())
    return frozenset(codes)


def _path_rule_violation_codes() -> frozenset[str]:
    """The codes ``PathRuleViolation`` raises with a call-site-specific name.

    ``PathRuleViolation`` names a more specific code than its own class
    attribute at a handful of call sites in ``manifest.py``, assigned on
    the instance rather than declared on the class, so
    ``_descendant_codes`` can't see them. Reading them out of the source
    that raises them - instead of maintaining a second, hand-kept list -
    means a call site added there without a matching row in
    ``design/api.html`` still shows up as an undocumented code rather than
    disappearing the way the six it replaces once did.
    """
    tree = ast.parse(inspect.getsource(catalog_manifest))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "PathRuleViolation" or len(node.args) != 2:
            continue
        code_argument = node.args[0]
        if isinstance(code_argument, ast.Constant) and isinstance(code_argument.value, str):
            codes.add(code_argument.value)
    return frozenset(codes)


def wire_error_codes() -> frozenset[str]:
    """Every code this service can put on the wire."""
    codes = {HTTPStatus(status).name for status in FRAMEWORK_STATUSES}
    codes.update({VALIDATION_CODE, INTERNAL_CODE})
    codes.update(_path_rule_violation_codes())
    for base in (DomainError, AuthError, RoleError):
        codes.update(_descendant_codes(base))
    return frozenset(codes)


PROBLEM_SCHEMA = {"$ref": "#/components/schemas/Problem"}


def problem_response(description: str) -> dict[str, object]:
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
