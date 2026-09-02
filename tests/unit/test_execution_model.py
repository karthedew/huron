"""The event-loop/threadpool boundary: which of the 52 operations block the
loop and are declared ``def`` (or wrap their one blocking call in
``asyncify``), and the invariant that keeps ``HierarchyRepository``'s
lock-protected writes safe to run from worker threads - no ``await`` ever
appears inside a method that holds ``self._lock``."""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import huron.service.api as api_package
import huron.service.api.app as app_module
from huron.pkg.auth import make_credential as real_make_credential
from huron.pkg.auth import verify_password as real_verify_password
from huron.service.api.app import create_app
from huron.service.api.routes.auth.endpoints import login
from huron.service.api.routes.v1.endpoints import users
from huron.service.api.settings import ApiSettings, ClassificationValue

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from fastapi import FastAPI

    from huron.pkg.auth import CredentialRecord
    from huron.service.api.repository import HierarchyRepository

pytestmark = pytest.mark.unit

REPOSITORY_MODULE = Path(__file__).resolve().parents[2] / "src/huron/service/api/repository.py"

#: The execution-model disposition of every path operation FastAPI
#: registers, named by its handler function (unique across the tier) and
#: mapped to whether the handler is a coroutine function. The four
#: documentation routes (``/docs``, ``/docs/oauth2-redirect``,
#: ``/openapi.json``, ``/redoc``) are framework-provided and excluded - the
#: table covers the 52 this service defines.
EXPECTED_COROUTINE_FUNCTION = {
    "healthz": True,
    "readyz": True,
    "search_unavailable": True,
    "password_login": True,
    "logout": True,
    "oidc_start": True,
    "oidc_callback": True,
    "session_info": True,
    "providers": True,
    "create_organization": False,
    "list_organizations": True,
    "get_organization": True,
    "patch_organization": False,
    "create_project": False,
    "list_projects": True,
    "get_project": True,
    "patch_project": False,
    "create_dataset": False,
    "list_datasets": True,
    "get_dataset": True,
    "patch_dataset": False,
    "create_release": False,
    "list_releases": True,
    "resolve_release": True,
    "list_layers": True,
    "create_write_intent": True,
    "list_roles": True,
    "list_system_bindings": True,
    "create_system_binding": True,
    "revoke_system_binding": True,
    "create_organization_binding": True,
    "list_organization_bindings": True,
    "revoke_organization_binding": True,
    "create_project_binding": True,
    "list_project_bindings": True,
    "revoke_project_binding": True,
    "create_dataset_binding": True,
    "list_dataset_bindings": True,
    "revoke_dataset_binding": True,
    "create_service_account": True,
    "list_service_accounts": True,
    "issue_service_account_key": True,
    "disable_service_account": True,
    "create_policy": True,
    "list_policies": True,
    "attach_to_organization": True,
    "attach_to_project": True,
    "attach_to_dataset": True,
    "issue_api_key": True,
    "create_user": True,
    "set_password": True,
    "disable_user": True,
}

DOCUMENTATION_ENDPOINTS = frozenset(
    {"swagger_ui_html", "swagger_ui_redirect", "openapi", "redoc_html"}
)


def _settings(tmp_path: Path, *, bootstrap_platform_owner: str | None = None) -> ApiSettings:
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner=bootstrap_platform_owner,
    )


def _built_app(tmp_path: Path) -> FastAPI:
    return create_app(settings=_settings(tmp_path))


def _operations(app: FastAPI) -> Iterator[Callable[..., object]]:
    """Every path operation FastAPI will actually route to, including those
    nested inside an included router - ``app.routes`` alone stops at the
    router boundary and never reaches the endpoints inside it."""
    routes: list[object] = list(app.routes)
    while routes:
        route = routes.pop()
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            routes.extend(nested_router.routes)
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            yield endpoint


def test_the_route_table_has_exactly_the_operations_this_service_defines(
    tmp_path: Path,
) -> None:
    names = {op.__name__ for op in _operations(_built_app(tmp_path))}
    assert names - DOCUMENTATION_ENDPOINTS == set(EXPECTED_COROUTINE_FUNCTION)


def test_every_operation_s_async_keyword_matches_the_execution_model_disposition(
    tmp_path: Path,
) -> None:
    actual = {
        op.__name__: inspect.iscoroutinefunction(op)
        for op in _operations(_built_app(tmp_path))
        if op.__name__ not in DOCUMENTATION_ENDPOINTS
    }
    assert actual == EXPECTED_COROUTINE_FUNCTION


def _event_loop_is_running() -> bool:
    """Whether the calling thread is the one currently driving an ``asyncio``
    event loop - the distinction that matters here, since a spawned worker
    thread is not the main thread but has no loop of its own either."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_the_three_blocking_calls_execute_off_the_event_loop_thread(tmp_path: Path) -> None:
    """``password_login``, ``create_user`` and ``set_password`` stay
    ``async def`` because they also await store calls, so their one blocking
    call must run on a worker thread rather than the event loop."""
    ran_on_the_event_loop: list[bool] = []

    def _tracking_verify_password(record: CredentialRecord | None, password: str) -> bool:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_verify_password(record, password)

    def _tracking_make_credential(
        principal_id: UUID, password: str, *, updated_by: str
    ) -> CredentialRecord:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_make_credential(principal_id, password, updated_by=updated_by)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    headers = {"X-Huron-Subject": "root"}
    with (
        patch.object(login, "verify_password", _tracking_verify_password),
        patch.object(users, "make_credential", _tracking_make_credential),
        TestClient(create_app(settings=settings)) as client,
    ):
        client.post("/auth/login", json={"username": "nobody", "password": "wrong-password"})
        created = client.post(
            "/api/v1/users",
            json={"username": "eve", "display_name": "Eve", "password": "a-strong-password"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        principal_id = created.json()["id"]
        reset = client.put(
            f"/api/v1/users/{principal_id}/password",
            json={"password": "another-strong-password"},
            headers=headers,
        )
        assert reset.status_code == 200, reset.text

    assert ran_on_the_event_loop == [False, False, False]


def test_readyz_s_raw_store_stat_executes_off_the_event_loop_thread(tmp_path: Path) -> None:
    """``readyz`` is ``async def`` - it also awaits the database check - so
    the raw-store stat's off-loop guarantee no longer falls out of the
    disposition table above; it comes only from the ``asyncify`` wrapping
    around the call site in ``app.py``, which this pins directly."""
    ran_on_the_event_loop: list[bool] = []
    real_raw_store_failure = app_module._raw_store_failure

    def _tracking_raw_store_failure(repository: HierarchyRepository) -> str | None:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_raw_store_failure(repository)

    with (
        patch.object(app_module, "_raw_store_failure", _tracking_raw_store_failure),
        TestClient(create_app(settings=_settings(tmp_path))) as client,
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    assert ran_on_the_event_loop == [False]


def test_no_asyncify_call_site_in_the_service_tier_is_cancellable() -> None:
    """A cancelled ``asyncify`` call would abandon a rawstore write or a
    credential hash mid-flight; every call site in the tier must accept the
    default (non-cancellable) behavior."""
    package_root = Path(api_package.__file__).resolve().parent
    for path in package_root.rglob("*.py"):
        assert "cancellable" not in path.read_text(), f"{path} passes cancellable="


# -- the lock-protected critical section admits no await --------------------


def _is_self_lock(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "_lock"
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "self"
    )


def _mutating_methods(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every ``HierarchyRepository`` method whose body takes ``self._lock`` -
    the read-check-write sequences that must stay atomic while the lock is
    held."""
    (repository_class,) = (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "HierarchyRepository"
    )
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in repository_class.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        holds_lock = any(
            isinstance(child, ast.With)
            and any(_is_self_lock(item.context_expr) for item in child.items)
            for child in ast.walk(node)
        )
        if holds_lock:
            methods.append(node)
    return methods


def test_no_await_appears_inside_a_mutating_hierarchy_repository_method() -> None:
    """The invariant the threading model depends on: a worker thread holding
    ``_lock`` across an ``fsync`` must never suspend there, or every other
    concurrent writer stalls behind it instead of behind the fsync alone."""
    tree = ast.parse(REPOSITORY_MODULE.read_text())
    mutating_methods = _mutating_methods(tree)
    assert len(mutating_methods) >= 7, "expected to find the repository's write methods"
    for method in mutating_methods:
        awaits = [child for child in ast.walk(method) if isinstance(child, ast.Await)]
        assert awaits == [], f"{method.name} awaits inside its _lock critical section"


LIST_QUERY_METHODS = frozenset(
    {"list_organizations", "list_projects", "list_datasets", "list_releases"}
)


def test_the_list_query_methods_never_acquire_the_lock() -> None:
    """These run on the event-loop thread; taking ``_lock`` there would block
    behind a writer's in-flight ``fsync`` and reintroduce the stall the
    threading model exists to remove."""
    tree = ast.parse(REPOSITORY_MODULE.read_text())
    (repository_class,) = (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "HierarchyRepository"
    )
    query_methods = [
        node
        for node in repository_class.body
        if isinstance(node, ast.FunctionDef) and node.name in LIST_QUERY_METHODS
    ]
    assert {method.name for method in query_methods} == LIST_QUERY_METHODS
    for method in query_methods:
        holds_lock = any(
            isinstance(child, ast.With)
            and any(_is_self_lock(item.context_expr) for item in child.items)
            for child in ast.walk(method)
        )
        assert not holds_lock, f"{method.name} acquires the lock"
