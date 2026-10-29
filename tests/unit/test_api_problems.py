"""The shared error contract: ``Problem``, ``problem()``, and the installed handlers.

Covers the seven handlers ``install_error_handlers`` wires onto an app and
``wire_error_codes`` - the walker that keeps the wire's code set honest
without a hand-maintained list that could fall out of sync with it.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from huron.applications.api.problems import (
    AUTHENTICATED_ERRORS,
    PROBLEM_MEDIA_TYPE,
    PROBLEM_SCHEMA,
    UNIVERSAL_ERRORS,
    Problem,
    install_error_handlers,
    problem,
    problem_response,
    wire_error_codes,
)
from huron.core.foundation.errors import AuthError, Forbidden
from huron.core.hierarchy.errors import SlugExists
from huron.core.security.roles import UnknownRole

pytestmark = pytest.mark.unit


class _SlugExistsRetryLater(SlugExists):
    """``SlugExists`` asking for a delay; it inherits the code, so the code walks never see it."""

    retry_after = 30


class _SlugExistsRetryAtOnce(SlugExists):
    """``SlugExists`` asking for a zero delay, which is still a delay to announce."""

    retry_after = 0


def _app() -> FastAPI:
    """A FastAPI app wired with ``install_error_handlers`` and one route per error family."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/domain")
    def _domain() -> None:
        raise SlugExists("organization slug already exists: astro")

    @app.get("/domain/retry-later")
    def _domain_retry_later() -> None:
        raise _SlugExistsRetryLater("organization slug already exists: astro")

    @app.get("/domain/retry-at-once")
    def _domain_retry_at_once() -> None:
        raise _SlugExistsRetryAtOnce("organization slug already exists: astro")

    @app.get("/auth")
    def _auth() -> None:
        raise AuthError("no usable credential")

    @app.get("/role")
    def _role() -> None:
        raise UnknownRole("no such role: ghost")

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/query")
    def _query(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get("/disconnect")
    def _disconnect() -> None:
        raise ClientDisconnect()

    return app


@pytest.fixture
def client() -> TestClient:
    """A ``TestClient`` over ``_app()`` that surfaces server errors as responses, not raises."""
    return TestClient(_app(), raise_server_exceptions=False)


def _assert_problem_shape(body: dict[str, object], *, status: int, code: str) -> None:
    """A problem body carries the given status and code, and a type URN derived from the code."""
    assert body.keys() >= {"type", "title", "status", "code", "detail"}
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:huron:error:{code.lower()}"


def test_domain_error_answers_its_own_status_and_code(client: TestClient) -> None:
    """A raised ``SlugExists`` answers 409 with the SLUG_EXISTS problem code."""
    response = client.get("/domain")
    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    _assert_problem_shape(response.json(), status=409, code="SLUG_EXISTS")


@pytest.mark.parametrize(
    ("path", "retry_after"),
    [("/domain/retry-later", "30"), ("/domain/retry-at-once", "0"), ("/domain", None)],
)
def test_problem_headers_carry_retry_after(
    client: TestClient, path: str, retry_after: str | None
) -> None:
    """A domain error's declared delay answers as ``Retry-After``; no delay sends no header.

    The delay changes nothing else: each answer keeps the status and code
    its class inherits.
    """
    response = client.get(path)
    assert response.status_code == 409
    _assert_problem_shape(response.json(), status=409, code="SLUG_EXISTS")
    assert response.headers.get("retry-after") == retry_after


def test_auth_error_answers_401_with_a_bearer_challenge(client: TestClient) -> None:
    """A raised ``AuthError`` answers 401 with a Bearer challenge and INVALID_CREDENTIAL."""
    response = client.get("/auth")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    _assert_problem_shape(response.json(), status=401, code="INVALID_CREDENTIAL")


def test_role_error_answers_422(client: TestClient) -> None:
    """A raised ``UnknownRole`` answers 422 with the UNKNOWN_ROLE problem code."""
    response = client.get("/role")
    assert response.status_code == 422
    _assert_problem_shape(response.json(), status=422, code="UNKNOWN_ROLE")


def test_a_client_disconnect_answers_400_with_the_framework_code(client: TestClient) -> None:
    """A raised ClientDisconnect answers 400 with the framework's BAD_REQUEST code."""
    response = client.get("/disconnect")
    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    _assert_problem_shape(response.json(), status=400, code="BAD_REQUEST")


def test_an_unrouted_path_answers_404_with_a_code(client: TestClient) -> None:
    """An unrouted path answers 404 with the NOT_FOUND problem code."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    _assert_problem_shape(response.json(), status=404, code="NOT_FOUND")


def test_the_wrong_method_on_a_real_path_answers_405_and_keeps_the_allow_header(
    client: TestClient,
) -> None:
    """The wrong method on a real path answers 405 with an Allow header naming GET."""
    response = client.post("/domain")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]
    _assert_problem_shape(response.json(), status=405, code="METHOD_NOT_ALLOWED")


def test_a_validation_failure_answers_422_with_the_pydantic_errors_encoded(
    client: TestClient,
) -> None:
    """A query-parameter validation failure answers 422 with pydantic's errors in its context."""
    response = client.get("/query", params={"n": "not-an-int"})
    assert response.status_code == 422
    body = response.json()
    _assert_problem_shape(body, status=422, code="REQUEST_INVALID")
    assert isinstance(body["context"]["errors"], list)
    assert body["context"]["errors"]


def test_an_unhandled_exception_answers_a_constant_500_and_logs_the_stack(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """An unhandled exception answers a fixed 500 detail, hiding its message, and logs the stack."""
    with caplog.at_level(logging.ERROR):
        response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    _assert_problem_shape(body, status=500, code="INTERNAL_ERROR")
    assert body["detail"] == "the request could not be completed"
    assert "kaboom" not in body["detail"]
    (record,) = [r for r in caplog.records if r.message == "unhandled error serving the request"]
    assert record.exc_info is not None


def test_problem_omits_context_when_none_is_given() -> None:
    """``problem()`` omits the context field entirely when none is given."""
    response = problem(409, "SLUG_EXISTS", "organization slug already exists: astro")
    assert response.status_code == 409
    assert response.media_type == PROBLEM_MEDIA_TYPE
    assert b"context" not in response.body


def test_problem_carries_context_when_given() -> None:
    """``problem()`` includes a context field when extra keyword context is given."""
    response = problem(400, "PATH_RULE_VIOLATION", "bad path", path="a/b")
    assert response.status_code == 400
    assert b'"context"' in response.body


def test_problem_model_defaults_context_to_none() -> None:
    """The ``Problem`` model defaults its context field to None."""
    body = Problem(type="urn:huron:error:x", title="X", status=400, code="X", detail="x")
    assert body.context is None


def test_wire_error_codes_includes_every_family_and_the_framework_statuses() -> None:
    """wire_error_codes lists the framework, domain, lake, auth and role error codes together."""
    codes = wire_error_codes()
    assert {"BAD_REQUEST", "NOT_FOUND", "METHOD_NOT_ALLOWED"} <= codes
    assert {"REQUEST_INVALID", "INTERNAL_ERROR"} <= codes
    assert "SLUG_EXISTS" in codes
    assert "FORBIDDEN" in codes
    assert Forbidden("x").code in codes
    assert "INVALID_CREDENTIAL" in codes
    assert "UNKNOWN_ROLE" in codes
    assert {"SCHEMA_INVALID", "SCHEMA_VERSION_EXISTS"} <= codes


def test_wire_error_codes_excludes_the_retired_dispatch_codes() -> None:
    """The abstract dispatch bases contribute no code of their own to wire_error_codes.

    This is what keeps a bare raise from silently reintroducing an
    undocumented code no static check would see.
    """
    codes = wire_error_codes()
    assert "DOMAIN_ERROR" not in codes
    assert "ROLE_VIOLATION" not in codes


def test_problem_response_refs_the_shared_problem_schema() -> None:
    """problem_response builds an OpenAPI entry whose schema is the shared PROBLEM_SCHEMA."""
    entry = problem_response("no usable credential")
    assert entry["description"] == "no usable credential"
    assert entry["content"][PROBLEM_MEDIA_TYPE]["schema"] == PROBLEM_SCHEMA


def test_authenticated_errors_extends_universal_errors_with_401_and_403() -> None:
    """AUTHENTICATED_ERRORS is a strict superset of UNIVERSAL_ERRORS, adding 401 and 403."""
    assert UNIVERSAL_ERRORS.keys() < AUTHENTICATED_ERRORS.keys()
    assert {401, 403} <= AUTHENTICATED_ERRORS.keys()
