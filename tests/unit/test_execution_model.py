"""The event-loop/threadpool boundary: which operations block, and where the loop must never stall.

Pins which of the 63 operations run on the event loop directly (they only
``await``) versus which wrap a blocking call in ``asyncify``: every
hierarchy, ingest and revision operation now awaits its store, so all 63
are coroutine functions, and the tripwire this module keeps is that the
raw store's filesystem calls stay off the loop thread.
"""

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
import huron.core.security._impl.identity as identity_module
from huron.applications.api.app import create_app
import huron.core.security._impl.password_authentication as login
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.security.password import make_credential as real_make_credential
from huron.core.security.password import verify_password as real_verify_password
from huron.core.rawstore import PosixRawStore
from tests.ingest_client import IngestClient, manifest_file
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    import os
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from fastapi import FastAPI

    from huron.core.security.password import CredentialRecord
    from huron.core.raw.ports import RawStore

pytestmark = pytest.mark.unit

#: The execution-model disposition of every path operation FastAPI
#: registers, named by its handler function (unique across the tier) and
#: mapped to whether the handler is a coroutine function. The four
#: documentation routes (``/docs``, ``/docs/oauth2-redirect``,
#: ``/openapi.json``, ``/redoc``) are framework-provided and excluded - the
#: table covers the 63 this service defines.
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
    "get_revision": True,
    "get_revision_manifest": True,
    "get_revision_file": True,
    "create_release": True,
    "list_releases": True,
    "resolve_release": True,
    "list_layers": True,
    "create_dataset_ingest_session": True,
    "create_project_ingest_session": True,
    "get_ingest_session": True,
    "heartbeat_ingest_session": True,
    "upload_part": True,
    "complete_upload": True,
    "verify_ingest_session": True,
    "commit_ingest_session": True,
    "abort_ingest_session": True,
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
    """Registered operations minus the four documentation routes equal exactly the 60 expected."""
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


def test_the_three_blocking_calls_execute_off_the_event_loop_thread(tmp_path: Path) -> None:
    """The blocking calls inside login, user creation and password reset run off the loop.

    ``password_login``, ``create_user`` and ``set_password`` stay
    ``async def`` because they also await store calls, so their one
    blocking call must run on a worker thread rather than the event loop.
    """
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
        patch.object(identity_module, "make_credential", _tracking_make_credential),
        TestClient(create_app(settings=settings, stores=memory_stores())) as client,
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
    """``readyz``'s raw-store stat still executes off the event-loop thread via ``asyncify``.

    ``readyz`` is ``async def`` - it also awaits the database check - so
    the raw-store stat's off-loop guarantee no longer falls out of the
    disposition table above; it comes only from the ``asyncify`` wrapping
    around the call site in ``app.py``, which this pins directly.
    """
    ran_on_the_event_loop: list[bool] = []
    real_raw_store_failure = app_module._raw_store_failure

    def _tracking_raw_store_failure(raw_store: RawStore) -> str | None:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_raw_store_failure(raw_store)

    with (
        patch.object(app_module, "_raw_store_failure", _tracking_raw_store_failure),
        TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client,
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    assert ran_on_the_event_loop and not any(ran_on_the_event_loop)


def test_the_upload_route_s_write_part_executes_off_the_event_loop_thread(tmp_path: Path) -> None:
    """The upload route's positional write still executes off the event-loop thread.

    ``upload_part`` is ``async def`` - it also awaits the ledger update -
    so the off-loop guarantee for the raw store's write comes only from
    the ``asyncify`` wrapping inside ``IngestService``, which this pins
    directly by driving one real upload through the route.
    """
    ran_on_the_event_loop: list[bool] = []
    real_write_part = PosixRawStore.write_part

    def _tracking_write_part(self: PosixRawStore, *args: object, **kwargs: object) -> str:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_write_part(self, *args, **kwargs)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with (
        patch.object(PosixRawStore, "write_part", _tracking_write_part),
        TestClient(create_app(settings=settings, stores=memory_stores())) as client,
    ):
        ingest = IngestClient(client)
        _, dataset_id = ingest.developer_dataset()
        session = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
        file_id = session["files"][0]["file_id"]

        response = ingest.put_part(file_id, 1, b"hello")

    assert response.status_code == 200, response.text
    assert ran_on_the_event_loop and not any(ran_on_the_event_loop)


def test_the_commit_route_s_envelope_publication_executes_off_the_event_loop_thread(
    tmp_path: Path,
) -> None:
    """The commit route's envelope publication still executes off the event-loop thread.

    ``commit_ingest_session`` is ``async def`` - it also awaits the
    recording transaction - so the off-loop guarantee for the envelope's
    rename comes only from the ``asyncify`` wrapping inside
    ``IngestService``, which this pins directly by driving one real commit
    through the route.
    """
    ran_on_the_event_loop: list[bool] = []
    real_commit_envelope = PosixRawStore.commit_envelope

    def _tracking_commit_envelope(self: PosixRawStore, *args: object, **kwargs: object) -> None:
        ran_on_the_event_loop.append(_event_loop_is_running())
        real_commit_envelope(self, *args, **kwargs)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with (
        patch.object(PosixRawStore, "commit_envelope", _tracking_commit_envelope),
        TestClient(create_app(settings=settings, stores=memory_stores())) as client,
    ):
        ingest = IngestClient(client)
        _, dataset_id = ingest.developer_dataset()
        data = b"hello"
        session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
        ingest.put_part(session["files"][0]["file_id"], 1, data)
        verified = ingest.verify(session["id"]).json()

        response = ingest.commit(
            session["id"], verified["etag"], {"title": "Run", "creators": ["bob"]}
        )

    assert response.status_code == 201, response.text
    assert ran_on_the_event_loop and not any(ran_on_the_event_loop)


def test_the_file_download_s_stat_executes_off_the_event_loop_thread(tmp_path: Path) -> None:
    """The file-download route's stat still executes off the event-loop thread via asyncify.

    ``get_revision_file`` is ``async def`` - it also awaits the manifest
    read - so the off-loop guarantee for the payload file's stat comes
    only from the ``asyncify`` wrapping inside ``RevisionService``, which
    this pins directly by driving one real download through the route.
    """
    ran_on_the_event_loop: list[bool] = []
    real_stat = PosixRawStore.stat_document

    def _tracking_stat(self: PosixRawStore, path: Path) -> os.stat_result:
        ran_on_the_event_loop.append(_event_loop_is_running())
        return real_stat(self, path)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with (
        patch.object(PosixRawStore, "stat_document", _tracking_stat),
        TestClient(create_app(settings=settings, stores=memory_stores())) as client,
    ):
        ingest = IngestClient(client)
        _, revision_id = ingest.committed([("payload/a.bin", b"hello")])
        response = ingest.download(revision_id, "payload/a.bin")

    assert response.status_code == 200, response.text
    assert ran_on_the_event_loop and not any(ran_on_the_event_loop)


def test_no_asyncify_call_site_in_the_service_tier_is_cancellable() -> None:
    """No ``asyncify`` call site in the service tier passes ``cancellable=``.

    A cancelled ``asyncify`` call would abandon a rawstore write or a
    credential hash mid-flight; every call site in the tier must accept the
    default (non-cancellable) behavior.
    """
    package_root = Path(api_package.__file__).resolve().parent
    for path in package_root.rglob("*.py"):
        assert "cancellable" not in path.read_text(), f"{path} passes cancellable="
