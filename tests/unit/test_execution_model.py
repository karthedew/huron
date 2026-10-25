"""Service operations await storage; blocking credential and readiness calls run off the loop."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import huron.applications.api as api_package
import huron.applications.api.app as app_module
from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi import FastAPI

    from huron.core.catalog.ports import GenerationStorage

pytestmark = pytest.mark.unit

#: The execution-model disposition of every path operation FastAPI
#: registers, named by its handler function (unique across the tier) and
#: mapped to whether the handler is a coroutine function. The four
#: documentation routes (``/docs``, ``/docs/oauth2-redirect``,
#: ``/openapi.json``, ``/redoc``) are framework-provided and excluded - the
#: table covers every explicitly reviewed service operation.
EXPECTED_COROUTINE_FUNCTION = {
    "healthz": True,
    "readyz": True,
    "search_unavailable": True,
    "create_organization": True,
    "list_organizations": True,
    "get_organization": True,
    "patch_organization": True,
    "create_project": True,
    "list_projects": True,
    "get_project": True,
    "patch_project": True,
    "create_dataset": True,
    "list_datasets": True,
    "get_dataset": True,
    "patch_dataset": True,
    "list_layers": True,
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
    "disable_user": True,
}

DOCUMENTATION_ENDPOINTS = frozenset(
    {"swagger_ui_html", "swagger_ui_redirect", "openapi", "redoc_html"}
)


def _settings(tmp_path: Path, *, bootstrap_platform_owner: str | None = None) -> ApiSettings:
    """Build dev-headers ``ApiSettings`` at ``tmp_path``, with an optional bootstrap owner."""
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner=bootstrap_platform_owner,
    )


def _built_app(tmp_path: Path) -> FastAPI:
    """Build a fully wired FastAPI app over ``tmp_path``'s settings."""
    return create_app(settings=_settings(tmp_path), stores=memory_stores())


def _operations(app: FastAPI) -> Iterator[Callable[..., object]]:
    """Every path operation FastAPI will actually route to, across every included router.

    Includes those nested inside an included router - ``app.routes`` alone
    stops at the router boundary and never reaches the endpoints inside it.
    """
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
    """Registered service operations equal the explicitly reviewed inventory."""
    names = {op.__name__ for op in _operations(_built_app(tmp_path))}
    assert names - DOCUMENTATION_ENDPOINTS == set(EXPECTED_COROUTINE_FUNCTION)


def test_every_operation_s_async_keyword_matches_the_execution_model_disposition(
    tmp_path: Path,
) -> None:
    """Every operation's ``async def``/``def`` keyword matches its declared disposition."""
    actual = {
        op.__name__: inspect.iscoroutinefunction(op)
        for op in _operations(_built_app(tmp_path))
        if op.__name__ not in DOCUMENTATION_ENDPOINTS
    }
    assert actual == EXPECTED_COROUTINE_FUNCTION


def _event_loop_is_running() -> bool:
    """Return whether the calling thread currently drives an ``asyncio`` event loop.

    The distinction that matters here, since a spawned worker thread is not
    the main thread but has no loop of its own either.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_readyz_s_generation_store_stat_executes_off_the_event_loop_thread(tmp_path: Path) -> None:
    """``readyz``'s generation-store stat still executes off the event-loop thread via ``asyncify``.

    ``readyz`` is ``async def`` - it also awaits the database check - so
    the generation-store stat's off-loop guarantee no longer falls out of the
    disposition table above; it comes only from the ``asyncify`` wrapping
    around the call site in ``app.py``, which this pins directly.
    """
    ran_on_the_event_loop: list[bool] = []
    real_generation_store_failure = app_module._generation_store_failure

    def _tracking_generation_store_failure(generations: GenerationStorage) -> str | None:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_generation_store_failure(generations)

    with (
        patch.object(app_module, "_generation_store_failure", _tracking_generation_store_failure),
        TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client,
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    assert ran_on_the_event_loop and not any(ran_on_the_event_loop)


def test_no_asyncify_call_site_in_the_service_tier_is_cancellable() -> None:
    """No ``asyncify`` call site in the service tier passes ``cancellable=``.

    A cancelled ``asyncify`` call would abandon filesystem work
    mid-flight; every call site in the tier must accept the
    default (non-cancellable) behavior.
    """
    package_root = Path(api_package.__file__).resolve().parent
    for path in package_root.rglob("*.py"):
        assert "cancellable" not in path.read_text(), f"{path} passes cancellable="
