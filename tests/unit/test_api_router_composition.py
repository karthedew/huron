"""Properties of the router tree itself, as opposed to any one route's business behavior.

The credential requirement inherited from the versioned router reaches
routes nested inside a further-included router with no per-operation
declaration, a capability guard declared on both a router and a parameter
resolves through one bound closure rather than two, the OpenAPI document
carries the resource-grained tag set, and the ``responses={}`` error
contract merges rather than replaces as it descends the router tree.
"""

from __future__ import annotations

import ast
import inspect
import re
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.security._impl import access as decisions
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path
    from types import ModuleType

    from huron.core.security.rules import Binding, Decision, Principal, Scope

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path, *, bootstrap_platform_owner: str | None = None) -> ApiSettings:
    """An ApiSettings with dev-headers auth and an optional bootstrapped platform owner."""
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner=bootstrap_platform_owner,
    )


def test_a_route_two_routers_below_v1_still_requires_a_credential(tmp_path: Path) -> None:
    """A route with no guard of its own still requires a credential from its router ancestors.

    ``list_organization_bindings`` declares no guard of its own at all -
    it is reachable only through ``bindings.organization_bindings``, itself
    included under the ``/api/v1`` router - so a ``401`` here proves the
    credential requirement propagates through two levels of ``include_router``
    rather than needing a guard written at the leaf.
    """
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get(
            f"/api/v1/organizations/{uuid4()}/bindings",
        )
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_user_disablement_has_transport_and_core_guards(
    tmp_path: Path,
) -> None:
    """The router and domain independently authorize user disablement."""
    calls: list[str] = []
    real_decide = decisions.decide

    def counting_decide(
        bindings: tuple[Binding, ...] | list[Binding],
        principal: Principal,
        capability: str,
        scope: Scope,
        *,
        layer: str | None = None,
        now: datetime | None = None,
    ) -> Decision:
        calls.append(capability)
        return real_decide(bindings, principal, capability, scope, layer=layer, now=now)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with (
        patch.object(decisions, "decide", counting_decide),
        TestClient(create_app(settings=settings, stores=memory_stores())) as client,
    ):
        response = client.post(
            f"/api/v1/users/{uuid4()}/disable",
            headers={"X-Huron-Subject": "root", "Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 404
    assert calls == ["user.manage", "user.manage"]


def test_a_dataset_scoped_binding_capability_bound_on_router_and_parameter_decides_once(
    tmp_path: Path,
) -> None:
    """The bind-once invariant also holds for a factory-built, dataset-scoped guard.

    The same bind-once invariant for a scope whose guard is built from a
    factory called at both the router (``dataset_bindings``) and the
    parameter (``create_dataset_binding``'s ``actor``) - both must reference
    one ``require_dataset("rbac.binding_manage")`` closure.
    """
    calls: list[str] = []
    real_decide = decisions.decide

    def counting_decide(
        bindings: tuple[Binding, ...] | list[Binding],
        principal: Principal,
        capability: str,
        scope: Scope,
        *,
        layer: str | None = None,
        now: datetime | None = None,
    ) -> Decision:
        calls.append(capability)
        return real_decide(bindings, principal, capability, scope, layer=layer, now=now)

    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    headers = {"X-Huron-Subject": "root", "Idempotency-Key": str(uuid4())}
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        organization_id = client.post(
            "/api/v1/organizations", json={"slug": "astro-org", "title": "Astro"}, headers=headers
        ).json()["id"]
        project_id = client.post(
            f"/api/v1/organizations/{organization_id}/projects",
            json={"slug": "sims-proj", "title": "Sims", "data_classification": "open"},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        ).json()["id"]
        dataset_id = client.post(
            f"/api/v1/projects/{project_id}/datasets",
            json={
                "slug": "run-0001",
                "title": "Run",
                "profile_name": "profile",
                "profile_version": "1",
            },
            headers={**headers, "Idempotency-Key": str(uuid4())},
        ).json()["id"]

        with patch.object(decisions, "decide", counting_decide):
            response = client.post(
                f"/api/v1/datasets/{dataset_id}/bindings",
                json={"principal": "user:bob", "role": "developer"},
                headers=headers,
            )
    assert response.status_code == 201
    assert calls == ["rbac.binding_manage", "rbac.binding_manage"]


def test_the_openapi_document_carries_the_resource_grained_tags(tmp_path: Path) -> None:
    """The OpenAPI document tags one per resource rather than one per module.

    ``role-bindings`` and ``service-accounts`` are distinct groups.
    """
    app = create_app(settings=_settings(tmp_path), stores=memory_stores())
    schema = app.openapi()
    tags: set[str] = set()
    for methods in schema["paths"].values():
        for operation in methods.values():
            tags.update(operation.get("tags", []))
    assert len(tags) == 11
    assert "auth" not in tags
    assert tags == {
        "organizations",
        "projects",
        "datasets",
        "roles",
        "role-bindings",
        "service-accounts",
        "policies",
        "policy-attachments",
        "api-keys",
        "users",
        "search",
    }


def test_a_credential_field_appears_only_on_the_two_key_issuance_responses(
    tmp_path: Path,
) -> None:
    """``secret`` appears only on the two key-issuance response schemas, never as a hash.

    ``secret`` is the plaintext of a freshly minted API key or
    service-account key, shown exactly once. No other schema in the
    document may declare ``secret`` or the stored hash it is never
    derived from.
    """
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    schemas = schema["components"]["schemas"]
    carrying_secret = {
        name for name, definition in schemas.items() if "secret" in definition.get("properties", {})
    }
    assert carrying_secret == {"IssuedApiKey", "IssuedServiceAccountKey"}
    for definition in schemas.values():
        assert "secret_sha256" not in definition.get("properties", {})


def test_the_problem_schema_is_registered_exactly_once(tmp_path: Path) -> None:
    """``Problem`` is registered in the schema components exactly once, via an explicit override.

    ``Problem`` backs no 2xx response, so nothing would put it in
    ``components.schemas`` without the explicit ``app.openapi()`` override -
    and every declared error response must resolve its ``$ref`` against
    that one entry, not a per-operation copy.
    """
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    schemas = schema["components"]["schemas"]
    assert list(schemas).count("Problem") == 1
    assert schemas["Problem"]["required"] == ["type", "title", "status", "code", "detail"]


@pytest.mark.parametrize(
    ("resource", "parameter", "leaf", "creation_path"),
    [
        ("organizations", "organization_id", "Organization", "/api/v1/organizations"),
        ("projects", "project_id", "Project", "/api/v1/organizations/{organization_id}/projects"),
        ("datasets", "dataset_id", "Dataset", "/api/v1/projects/{project_id}/datasets"),
    ],
)
def test_hierarchy_keeps_named_patch_and_response_schemas(
    tmp_path: Path, resource: str, parameter: str, leaf: str, creation_path: str
) -> None:
    """Shared PATCH fields retain named leaf inputs and filtered public views on every operation."""
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    schemas = schema["components"]["schemas"]
    assert "DescriptionPatch" not in schemas
    patch_schema = schemas[f"Patch{leaf}"]
    assert patch_schema["title"] == f"Patch{leaf}"
    assert f"PATCH /{resource}/{{{parameter}}}" in patch_schema["description"]
    assert set(patch_schema["properties"]) == {"slug", "title", "description"}
    assert not patch_schema.get("required")
    for field in patch_schema["properties"].values():
        assert "default" not in field
        assert field["anyOf"] == [{"type": "string"}, {"type": "null"}]
    path = schema["paths"][f"/api/v1/{resource}/{{{parameter}}}"]
    body = path["patch"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": f"#/components/schemas/Patch{leaf}"}
    for operation, status in (
        (path["get"], "200"),
        (path["patch"], "200"),
        (schema["paths"][creation_path]["post"], "201"),
    ):
        result = operation["responses"][status]["content"]["application/json"]["schema"]
        assert result == {"$ref": f"#/components/schemas/{leaf}View"}
    assert "generation" not in schemas[f"{leaf}View"]["properties"]


@pytest.mark.parametrize(
    ("resource", "parameter"),
    [
        ("organizations", "organization_id"),
        ("projects", "project_id"),
        ("datasets", "dataset_id"),
    ],
)
def test_catalog_guards_keep_resource_ids_as_named_path_parameters(
    tmp_path: Path, resource: str, parameter: str
) -> None:
    """Shared guards preserve each route's required UUID path parameter without query inputs."""
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    operation = schema["paths"][f"/api/v1/{resource}/{{{parameter}}}"]["patch"]
    path_parameters = [item for item in operation["parameters"] if item["in"] == "path"]
    assert len(path_parameters) == 1
    assert path_parameters[0]["name"] == parameter
    assert path_parameters[0]["required"] is True
    assert path_parameters[0]["schema"]["format"] == "uuid"
    assert all(item["name"] != "resource_id" for item in operation["parameters"])


def test_every_declared_error_response_refs_the_shared_problem_schema(tmp_path: Path) -> None:
    """Every declared 4xx/5xx response across the document refs the shared Problem schema."""
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    for methods in schema["paths"].values():
        for operation in methods.values():
            for status, response in operation["responses"].items():
                if status == "default" or int(status) < 400:
                    continue
                content = response["content"]
                assert list(content) == ["application/problem+json"]
                assert content["application/problem+json"]["schema"] == {
                    "$ref": "#/components/schemas/Problem"
                }


def test_router_level_responses_are_inherited_two_levels_deep(tmp_path: Path) -> None:
    """Router-declared error responses inherit down two levels of ``include_router`` nesting.

    ``organization_bindings`` is included into ``v1.router``, which is in
    turn included into the app - two levels - and declares no ``responses=``
    of its own, so the ``401``/``403``/``422``/``500`` its operations answer
    with come entirely from the ``/api/v1`` router.
    """
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    binding_create = schema["paths"]["/api/v1/organizations/{organization_id}/bindings"]["post"]
    assert {401, 403, 422, 500} <= {int(status) for status in binding_create["responses"]}


def test_per_operation_responses_add_to_the_inherited_set_rather_than_replace_it(
    tmp_path: Path,
) -> None:
    """A route's own declared responses union with the router's inherited set, replacing neither.

    ``create_organization`` declares only its own ``409``; the full
    response set on the generated operation is that addition union the
    ``/api/v1`` router's inherited ``401``/``403``/``422``/``500``, not one
    or the other.
    """
    schema = create_app(settings=_settings(tmp_path), stores=memory_stores()).openapi()
    create_organization = schema["paths"]["/api/v1/organizations"]["post"]
    assert {int(status) for status in create_organization["responses"]} == {
        201,
        401,
        403,
        409,
        422,
        500,
    }


def _decorator_response_statuses(module: ModuleType) -> set[int]:
    """The status codes a module's route decorators declare via their own ``responses={...}``.

    The integer status codes named in a ``responses={...}`` keyword on any
    decorator in ``module``'s source - the operation's own declarations,
    before the router's inherited set is merged in.
    """
    tree = ast.parse(inspect.getsource(module))
    statuses: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            for keyword in decorator.keywords:
                if keyword.arg != "responses" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, int):
                        statuses.add(key.value)
    return statuses


def test_no_v1_operation_redeclares_a_status_the_v1_router_already_covers() -> None:
    """No v1 operation redeclares a status already covered by AUTHENTICATED_ERRORS on the router.

    ``AUTHENTICATED_ERRORS`` (401/403/422/500) is declared once, on
    ``routes/v1/__init__.py``'s router - repeating any of them on an
    operation's own ``responses=`` would defeat the point of declaring it
    there.
    """
    from huron.applications.api.routes.v1.endpoints import (
        api_keys,
        bindings,
        datasets,
        organizations,
        policies,
        projects,
        roles,
        search,
        service_accounts,
        users,
    )

    for module in (
        api_keys,
        bindings,
        datasets,
        organizations,
        policies,
        projects,
        roles,
        search,
        service_accounts,
        users,
    ):
        assert _decorator_response_statuses(module) & {401, 403, 422, 500} == set()


LEGACY_OPERATIONS = {
    "/api/v1/organizations": ["get", "post"],
    "/api/v1/organizations/{organization_id}": ["get", "patch"],
    "/api/v1/organizations/{organization_id}/projects": ["get", "post"],
    "/api/v1/projects/{project_id}": ["get", "patch"],
    "/api/v1/projects/{project_id}/datasets": ["get", "post"],
    "/api/v1/datasets/{dataset_id}": ["get", "patch"],
    "/api/v1/datasets/{dataset_id}/layers": ["get"],
    "/api/v1/roles": ["get"],
    "/api/v1/bindings": ["get", "post"],
    "/api/v1/bindings/{binding_id}": ["delete"],
    "/api/v1/organizations/{organization_id}/bindings": ["get", "post"],
    "/api/v1/organizations/{organization_id}/bindings/{binding_id}": ["delete"],
    "/api/v1/projects/{project_id}/bindings": ["get", "post"],
    "/api/v1/projects/{project_id}/bindings/{binding_id}": ["delete"],
    "/api/v1/datasets/{dataset_id}/bindings": ["get", "post"],
    "/api/v1/datasets/{dataset_id}/bindings/{binding_id}": ["delete"],
    "/api/v1/organizations/{organization_id}/service-accounts": ["get", "post"],
    "/api/v1/organizations/{organization_id}/service-accounts/{principal_id}/api-keys": ["post"],
    "/api/v1/organizations/{organization_id}/service-accounts/{principal_id}/disable": ["post"],
    "/api/v1/policies": ["get", "post"],
    "/api/v1/organizations/{organization_id}/policy-attachments": ["post"],
    "/api/v1/projects/{project_id}/policy-attachments": ["post"],
    "/api/v1/datasets/{dataset_id}/policy-attachments": ["post"],
    "/api/v1/auth/api-keys": ["post"],
    "/api/v1/users/{principal_id}/disable": ["post"],
    "/api/v1/search": ["get"],
}


def test_the_legacy_v1_router_serves_exactly_its_operations(client: TestClient) -> None:
    """The legacy surface retains every reviewed path and method, with no additions."""
    paths = client.get("/openapi.json").json()["paths"]
    actual = {
        path: sorted(methods) for path, methods in paths.items() if path.startswith("/api/v1/")
    }
    assert actual == LEGACY_OPERATIONS
    assert not any(path.startswith("/auth") for path in paths)
    assert sum(map(len, actual.values())) == 38


def test_every_legacy_v1_operation_refuses_an_anonymous_request(client: TestClient) -> None:
    """Every legacy operation rejects missing credentials before resolving resource access."""
    paths = client.get("/openapi.json").json()["paths"]
    for path, methods in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        target = re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), path)
        for method in methods:
            response = client.request(method, target)
            assert response.status_code == 401, (method, path, response.text)
            assert response.headers["content-type"] == "application/problem+json"
            assert response.json()["status"] == 401


def test_the_retired_bridge_prefix_has_no_route(client: TestClient) -> None:
    """The former bridge URL is absent even when a legacy credential is supplied."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/raw-web") for path in paths)
    for headers in ({}, {"X-Huron-Subject": "root"}):
        response = client.get(f"/api/raw-web/uploads/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
