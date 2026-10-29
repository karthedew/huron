"""Error codes and problem documents."""

import pytest

from huron.pkg.errors import (
    FORBIDDEN,
    Conflict,
    ErrorCodes,
    Forbidden,
    Invalid,
    NotFound,
    Unauthenticated,
    Unavailable,
    error_codes,
)


def test_registry_refuses_duplicates_and_lists_sorted() -> None:
    registry = ErrorCodes()
    registry.register("B_CODE", 409, "B")
    registry.register("A_CODE", 400, "A")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("A_CODE", 400, "A")
    assert [entry.code for entry in registry] == ["A_CODE", "B_CODE"]
    assert "A_CODE" in registry
    assert registry.get("B_CODE").status == 409


def test_shared_registry_holds_the_generic_codes() -> None:
    codes = {entry.code for entry in error_codes().all()}
    assert {"FORBIDDEN", "NOT_FOUND", "STATE_CONFLICT", "REQUEST_INVALID"} <= codes
    assert error_codes().get("FORBIDDEN") is FORBIDDEN


def test_problem_document_carries_code_status_and_context() -> None:
    error = Forbidden("no access", {"privilege": "CATALOG_READ"})
    document = error.problem("/api/v1/catalogs/x")
    assert document == {
        "type": "https://huron.dev/problems/forbidden",
        "title": "Forbidden",
        "status": 403,
        "detail": "no access",
        "code": "FORBIDDEN",
        "context": {"privilege": "CATALOG_READ"},
        "instance": "/api/v1/catalogs/x",
    }
    assert str(error) == "no access"


@pytest.mark.parametrize(
    ("error_type", "status"),
    [(Unauthenticated, 401), (NotFound, 404), (Conflict, 409), (Invalid, 422), (Unavailable, 503)],
)
def test_generic_errors_map_to_their_status(error_type: type[Exception], status: int) -> None:
    error = error_type("x")
    assert error.status == status  # type: ignore[attr-defined]
    assert "instance" not in error.problem()  # type: ignore[attr-defined]
    assert error.context == {}  # type: ignore[attr-defined]
