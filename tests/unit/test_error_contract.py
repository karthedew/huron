"""The error contract end to end: documented codes, statuses, uniform shape, and the base class.

``design/api.html`` §7 and the exception classes the service can actually
raise name the same codes; each code has exactly one declaring class; each
documented status matches the class that answers with it; every documented
disposition matches whether the tree actually raises the code anywhere; all
seven error handlers answer in the same shape; and the base class enforcing
all of this stays impossible to raise directly.
"""

from __future__ import annotations

import ast
from html.parser import HTMLParser
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from huron.applications.api.problems import (
    FRAMEWORK_STATUSES,
    PROBLEM_MEDIA_TYPE,
    install_error_handlers,
    wire_error_codes,
)
from huron.core.foundation.errors import AuthError, DomainError, ResourceNotFound
from huron.core.security.roles import RoleError, UnknownRole

if TYPE_CHECKING:
    from httpx import Response

pytestmark = pytest.mark.unit

API_HTML = Path(__file__).parents[2] / "design" / "api.html"


class _ErrorTableRow:
    """One parsed row of the documented error table: a code, a status and a disposition."""

    __slots__ = ("code", "disposition", "status")

    def __init__(self, code: str, status: int, disposition: str) -> None:
        self.code = code
        self.status = status
        self.disposition = disposition


class _ErrorTableParser(HTMLParser):
    """Reads the rows of ``design/api.html``'s ``<table id="error-codes">``.

    A row built entirely of ``<th>`` cells is the header and is dropped; the
    table's own markup is trusted to name a documented code first, its HTTP
    status second and its live/reserved disposition third.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_ErrorTableRow] = []
        self._in_table = False
        self._in_cell = False
        self._cell_text: list[str] = []
        self._row: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and ("id", "error-codes") in attrs:
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif self._in_table and tag in ("td", "th"):
            self._row.append(("".join(self._cell_text).strip(), tag))
            self._in_cell = False
        elif self._in_table and tag == "tr":
            if self._row and all(kind == "td" for _, kind in self._row):
                code, status, disposition = (text for text, _ in self._row[:3])
                self.rows.append(_ErrorTableRow(code, int(status), disposition))
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)


def _documented_rows() -> list[_ErrorTableRow]:
    """Parse ``design/api.html``'s error-codes table into its documented rows."""
    parser = _ErrorTableParser()
    parser.feed(API_HTML.read_text())
    return parser.rows


def _status_by_domain_error_code() -> dict[str, int]:
    """Every ``DomainError`` subclass's own code mapped to its status.

    Walks the live class tree rather than a fixed list, the same way
    ``wire_error_codes`` does, so this stays honest against the same
    subclasses the bijection assertion below checks.
    """
    mapping: dict[str, int] = {}
    stack = [DomainError]
    while stack:
        cls = stack.pop()
        code = cls.__dict__.get("code")
        if isinstance(code, str):
            mapping[code] = cls.status_code
        stack.extend(cls.__subclasses__())
    return mapping


def test_every_documented_code_has_a_class_and_every_class_has_a_row() -> None:
    """Every raisable error code is documented in §7, and every §7 row has a raising class."""
    documented = {row.code for row in _documented_rows()}
    raisable = wire_error_codes()
    undocumented = raisable - documented
    orphaned = documented - raisable
    assert not undocumented, f"codes raisable but not in design/api.html §7: {sorted(undocumented)}"
    assert not orphaned, f"§7 rows with no raisable code behind them: {sorted(orphaned)}"


def test_public_vocabularies_match_independent_classes() -> None:
    """Published vocabularies match actual exception declarations."""
    declared = set(_class_name_by_code())
    transport = {HTTPStatus(status).name for status in FRAMEWORK_STATUSES}
    assert wire_error_codes() == declared | transport | {"REQUEST_INVALID", "INTERNAL_ERROR"}


def test_domain_error_rows_document_their_class_status_code() -> None:
    """Every documented row for a ``DomainError`` code states that class's own status code."""
    status_by_code = _status_by_domain_error_code()
    mismatched = [
        (row.code, row.status, status_by_code[row.code])
        for row in _documented_rows()
        if row.code in status_by_code and row.status != status_by_code[row.code]
    ]
    assert not mismatched, f"§7 status disagrees with the raising class: {mismatched}"


def _declaring_classes_by_code() -> dict[str, list[type[Exception]]]:
    """Map each code to the live error classes that declare it as their own, in walk order.

    Walks the live subclass trees of ``DomainError``, ``AuthError`` and
    ``RoleError`` the same way ``wire_error_codes`` does. Only a class's own
    ``code`` counts: a subclass that inherits its code declares none.

    Returns:
        Each declared ``code`` string mapped to the classes that declare it.
    """
    mapping: dict[str, list[type[Exception]]] = {}
    for base in (DomainError, AuthError, RoleError):
        stack: list[type[Exception]] = [base]
        while stack:
            cls = stack.pop()
            code = cls.__dict__.get("code")
            if isinstance(code, str) and cls not in mapping.get(code, []):
                mapping.setdefault(code, []).append(cls)
            stack.extend(cls.__subclasses__())
    return mapping


def _class_name_by_code() -> dict[str, str]:
    """Map every code a live ``DomainError``, ``AuthError`` or ``RoleError`` subclass declares.

    A §7 row is matched to the class that actually answers it - never by
    CamelCasing the code back into a class name, which does not round-trip
    (``NOT_FOUND`` is ``ResourceNotFound``, not ``NotFound``).

    Returns:
        The declared ``code`` string mapped to the name of the class that
        declares it; a code no live class declares is absent.
    """
    return {code: classes[-1].__name__ for code, classes in _declaring_classes_by_code().items()}


def test_each_code_is_declared_by_exactly_one_class() -> None:
    """No two live error classes declare the same code, so each documented row names one class.

    ``_class_name_by_code`` keeps a single class per code; a second
    declaring class would make each check built on it depend on walk order.
    """
    shared = {
        code: sorted(f"{cls.__module__}.{cls.__qualname__}" for cls in classes)
        for code, classes in _declaring_classes_by_code().items()
        if len(classes) > 1
    }
    assert not shared, f"codes declared by more than one class: {shared}"


def _raise_site_class_names() -> frozenset[str]:
    """Collect the callee name of every ``raise <name>(...)`` statement under ``src/huron``.

    An ``ast`` walk of the source tree rather than a runtime probe, so a
    class with no raise site anywhere - reachable by this test run or not
    - cannot hide behind a documented row: every module's source is read,
    not only the ones this process happened to import.

    Returns:
        The set of names appearing as the callee of a ``raise name(...)``
        or ``raise module.name(...)`` statement anywhere under
        ``src/huron``.
    """
    root = Path(__file__).parents[2] / "src" / "huron"
    names: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return frozenset(names)


def test_live_rows_have_a_raise_site_and_reserved_rows_have_none() -> None:
    """A §7 row's disposition matches whether its class is actually raised anywhere in the tree.

    Framework-status rows (``FRAMEWORK_STATUSES``) are exempt: they answer
    from the router or the body-reading machinery, never from a raised
    class, so disposition has nothing to check them against.
    """
    class_by_code = _class_name_by_code()
    raise_sites = _raise_site_class_names()
    framework_codes = {HTTPStatus(status).name for status in FRAMEWORK_STATUSES}
    live_without_site = []
    reserved_with_site = []
    for row in _documented_rows():
        if row.code in framework_codes:
            continue
        class_name = class_by_code.get(row.code)
        if class_name is None:
            continue
        has_site = class_name in raise_sites
        if row.disposition == "live" and not has_site:
            live_without_site.append(row.code)
        elif row.disposition == "reserved" and has_site:
            reserved_with_site.append(row.code)
    assert not live_without_site, f"§7 live rows with no raise site: {live_without_site}"
    assert not reserved_with_site, f"§7 reserved rows with a raise site: {reserved_with_site}"


def test_every_auth_error_row_answers_401_and_every_role_error_row_answers_422() -> None:
    """Every ``AuthError`` code documents status 401; every ``RoleError`` code documents 422."""
    auth_codes = {AuthError.__dict__.get("code"), *(sub.code for sub in AuthError.__subclasses__())}
    role_codes = {sub.code for sub in RoleError.__subclasses__()}
    rows_by_code = {row.code: row for row in _documented_rows()}
    for code in auth_codes:
        assert rows_by_code[code].status == 401, f"{code} is an AuthError but §7 doesn't say 401"
    for code in role_codes:
        assert rows_by_code[code].status == 422, f"{code} is a RoleError but §7 doesn't say 422"


def test_domain_error_refuses_direct_instantiation() -> None:
    """Instantiating ``DomainError`` itself raises ``TypeError``, not a usable error."""
    with pytest.raises(TypeError, match="DomainError is abstract"):
        DomainError("x")


def _uniform_shape_app() -> FastAPI:
    """Build a minimal FastAPI app, wired with the shared handlers, with one route per error."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/resource/{item_id}")
    def _resource(item_id: str) -> None:
        raise ResourceNotFound(f"no such item: {item_id}")

    @app.get("/auth")
    def _auth() -> None:
        raise AuthError("no usable credential")

    @app.get("/role")
    def _role() -> None:
        raise UnknownRole("no such role: ghost")

    @app.get("/query")
    def _query(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/disconnect")
    def _disconnect() -> None:
        raise ClientDisconnect()

    return app


@pytest.fixture
def client() -> TestClient:
    """A ``TestClient`` for the uniform-shape app that returns server errors as responses."""
    return TestClient(_uniform_shape_app(), raise_server_exceptions=False)


def _assert_uniform_problem(response: Response, *, status: int) -> None:
    """Assert a response is a problem document with the given status and a raisable code."""
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body.keys() >= {"type", "title", "status", "code", "detail"}
    assert body["status"] == status
    assert body["code"] in wire_error_codes()


def test_a_domain_error_answers_uniformly(client: TestClient) -> None:
    """A ``DomainError`` (``ResourceNotFound``) answers as a uniform problem with its own status."""
    _assert_uniform_problem(client.get("/resource/missing"), status=404)


def test_an_auth_error_answers_uniformly(client: TestClient) -> None:
    """An ``AuthError`` answers as a uniform problem document with status 401."""
    _assert_uniform_problem(client.get("/auth"), status=401)


def test_a_role_error_answers_uniformly(client: TestClient) -> None:
    """A ``RoleError`` (``UnknownRole``) answers as a uniform problem document with status 422."""
    _assert_uniform_problem(client.get("/role"), status=422)


def test_an_unrouted_path_answers_uniformly(client: TestClient) -> None:
    """A path with no matching route still answers as a uniform 404 problem document."""
    _assert_uniform_problem(client.get("/does-not-exist"), status=404)


def test_a_request_validation_failure_answers_uniformly(client: TestClient) -> None:
    """A request validation failure still answers as a uniform 422 problem document."""
    _assert_uniform_problem(client.get("/query", params={"n": "not-an-int"}), status=422)


def test_an_unhandled_exception_answers_uniformly(client: TestClient) -> None:
    """An unhandled exception still answers as a uniform 500 problem document."""
    _assert_uniform_problem(client.get("/boom"), status=500)


def test_a_client_disconnect_answers_uniformly(client: TestClient) -> None:
    """A ``ClientDisconnect`` still answers as a uniform 400 problem document."""
    response = client.get("/disconnect")
    _assert_uniform_problem(response, status=400)
    assert response.json()["code"] == "BAD_REQUEST"
