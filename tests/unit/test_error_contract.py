"""The error contract as a whole: that ``design/api.html`` §7 and the
exception classes the service can actually raise name the same codes, that
each documented status matches the class that answers with it, that all six
error handlers answer in the same shape, and that the base class enforcing
all of this stays impossible to raise directly."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from huron.pkg.auth import AuthError
from huron.pkg.catalog.errors import DomainError, ResourceNotFound
from huron.pkg.rbac.roles import RoleError, UnknownRole
from huron.service.api.problems import (
    PROBLEM_MEDIA_TYPE,
    install_error_handlers,
    wire_error_codes,
)

if TYPE_CHECKING:
    from httpx import Response

pytestmark = pytest.mark.unit

API_HTML = Path(__file__).parents[2] / "design" / "api.html"


class _ErrorTableRow:
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
    documented = {row.code for row in _documented_rows()}
    raisable = wire_error_codes()
    undocumented = raisable - documented
    orphaned = documented - raisable
    assert not undocumented, f"codes raisable but not in design/api.html §7: {sorted(undocumented)}"
    assert not orphaned, f"§7 rows with no raisable code behind them: {sorted(orphaned)}"


def test_domain_error_rows_document_their_class_status_code() -> None:
    status_by_code = _status_by_domain_error_code()
    mismatched = [
        (row.code, row.status, status_by_code[row.code])
        for row in _documented_rows()
        if row.code in status_by_code and row.status != status_by_code[row.code]
    ]
    assert not mismatched, f"§7 status disagrees with the raising class: {mismatched}"


def test_every_auth_error_row_answers_401_and_every_role_error_row_answers_422() -> None:
    auth_codes = {AuthError.__dict__.get("code"), *(sub.code for sub in AuthError.__subclasses__())}
    role_codes = {sub.code for sub in RoleError.__subclasses__()}
    rows_by_code = {row.code: row for row in _documented_rows()}
    for code in auth_codes:
        assert rows_by_code[code].status == 401, f"{code} is an AuthError but §7 doesn't say 401"
    for code in role_codes:
        assert rows_by_code[code].status == 422, f"{code} is a RoleError but §7 doesn't say 422"


def test_domain_error_refuses_direct_instantiation() -> None:
    with pytest.raises(TypeError, match="DomainError is abstract"):
        DomainError("x")


def _uniform_shape_app() -> FastAPI:
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

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_uniform_shape_app(), raise_server_exceptions=False)


def _assert_uniform_problem(response: Response, *, status: int) -> None:
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body.keys() >= {"type", "title", "status", "code", "detail"}
    assert body["status"] == status
    assert body["code"] in wire_error_codes()


def test_a_domain_error_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/resource/missing"), status=404)


def test_an_auth_error_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/auth"), status=401)


def test_a_role_error_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/role"), status=422)


def test_an_unrouted_path_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/does-not-exist"), status=404)


def test_a_request_validation_failure_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/query", params={"n": "not-an-int"}), status=422)


def test_an_unhandled_exception_answers_uniformly(client: TestClient) -> None:
    _assert_uniform_problem(client.get("/boom"), status=500)
