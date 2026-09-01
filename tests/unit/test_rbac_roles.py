"""The role-model invariants that make the layer story trustworthy."""

from __future__ import annotations

from uuid import uuid4

import pytest

from huron.pkg.rbac import Decision, Principal, Scope, ScopeType, decide
from huron.pkg.rbac.roles import (
    CAPABILITIES,
    ROLES,
    SERVICE_ACCOUNT_CAPABILITIES,
    SERVICE_ACCOUNT_LAYERS,
    PrincipalKindNotAllowed,
    ScopeNotBindable,
    compile_binding,
    roles_granting_write,
    service_account_bindings,
    validate_binding,
)

pytestmark = pytest.mark.unit


def test_no_role_writes_silver_or_gold_and_all_roles_are_human_only() -> None:
    """Silver/gold writers are service accounts by construction.

    No role in the vocabulary carries silver/gold ``data.write`` and every
    role is holdable by users only, so no binding - however seeded - can
    put those writes in human hands. The only path to them is the intrinsic
    service-account authority below.
    """
    for layer in ("silver", "gold"):
        assert roles_granting_write(layer) == (), layer
    assert {role.code for role in roles_granting_write("raw")} == {"developer"}
    assert {role.code for role in roles_granting_write("bronze")} == {"developer"}
    for role in ROLES.values():
        assert role.allowed_principal_kinds == frozenset({"user"}), role.code


def test_service_accounts_hold_no_roles() -> None:
    for code in ROLES:
        with pytest.raises(PrincipalKindNotAllowed):
            validate_binding(code, "service_account", ScopeType.ORGANIZATION)


def test_service_account_authority_is_org_scoped_silver_gold_crud() -> None:
    """An SA's whole authority: dataset CRUD + silver/gold read/write, its org only."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    bindings = list(service_account_bindings("sa:org/loader", organization_id))
    feed = Principal("org/loader", kind="service_account")
    scope = Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=dataset_id,
    )
    for capability in SERVICE_ACCOUNT_CAPABILITIES:
        assert decide(bindings, feed, capability, scope) is Decision.ALLOW, capability
    for layer in SERVICE_ACCOUNT_LAYERS:
        assert decide(bindings, feed, "data.write", scope, layer=layer) is Decision.ALLOW, layer
        assert decide(bindings, feed, "data.read", scope, layer=layer) is Decision.ALLOW, layer
    for layer in ("raw", "bronze"):
        assert decide(bindings, feed, "data.write", scope, layer=layer) is Decision.DENY, layer
        assert decide(bindings, feed, "data.read", scope, layer=layer) is Decision.DENY, layer
    assert decide(bindings, feed, "rbac.binding_manage", scope) is Decision.DENY
    assert decide(bindings, feed, "release.create", scope) is Decision.DENY
    foreign_scope = Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=uuid4(),
        project_id=project_id,
        dataset_id=dataset_id,
    )
    assert decide(bindings, feed, "data.write", foreign_scope, layer="silver") is Decision.DENY
    assert decide(bindings, feed, "dataset.create", foreign_scope) is Decision.DENY


def test_admin_roles_carry_no_data_write() -> None:
    for code in ("project_admin", "organization_admin", "platform_owner"):
        assert not any(grant.capability == "data.write" for grant in ROLES[code].layer_grants), code


def test_platform_owner_binds_only_at_system_scope() -> None:
    with pytest.raises(ScopeNotBindable):
        validate_binding("platform_owner", "user", ScopeType.ORGANIZATION)
    validate_binding("platform_owner", "user", ScopeType.SYSTEM)


def test_every_role_capability_is_in_the_vocabulary() -> None:
    for role in ROLES.values():
        assert role.capabilities <= CAPABILITIES, role.code
        for grant in role.layer_grants:
            assert grant.capability in CAPABILITIES, role.code


def test_compiled_developer_writes_raw_not_silver() -> None:
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    bindings = list(
        compile_binding(
            "developer",
            principal_identifier="user:bob",
            principal_kind="user",
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
        )
    )
    bob = Principal("bob")
    scope = Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=dataset_id,
    )
    assert decide(bindings, bob, "data.write", scope, layer="raw") is Decision.ALLOW
    assert decide(bindings, bob, "data.write", scope, layer="silver") is Decision.DENY
    assert decide(bindings, bob, "data.read", scope, layer="gold") is Decision.ALLOW
    assert decide(bindings, bob, "dataset.create", scope) is Decision.ALLOW
    assert decide(bindings, bob, "rbac.binding_manage", scope) is Decision.DENY


def test_organization_binding_inherits_downward() -> None:
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    bindings = list(
        compile_binding(
            "reader",
            principal_identifier="group:physics",
            principal_kind="user",
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
        )
    )
    member = Principal("carol", groups=frozenset({"physics"}))
    scope = Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=dataset_id,
    )
    assert decide(bindings, member, "data.read", scope, layer="silver") is Decision.ALLOW
    other_scope = Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=uuid4(),
        project_id=project_id,
        dataset_id=dataset_id,
    )
    assert decide(bindings, member, "data.read", other_scope, layer="silver") is Decision.DENY


def test_service_account_principal_uses_sa_prefix() -> None:
    account = Principal("alpha/loader", kind="service_account")
    assert "sa:alpha/loader" in account.identifiers
    assert "user:alpha/loader" not in account.identifiers
