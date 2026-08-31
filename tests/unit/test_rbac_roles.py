"""The role-model invariants that make the layer story trustworthy."""

from __future__ import annotations

from uuid import uuid4

import pytest

from huron.pkg.rbac import Decision, Principal, Scope, ScopeType, decide
from huron.pkg.rbac.roles import (
    CAPABILITIES,
    ROLES,
    PrincipalKindNotAllowed,
    ScopeNotBindable,
    compile_binding,
    roles_granting_write,
    validate_binding,
)

pytestmark = pytest.mark.unit


def test_silver_and_gold_writes_are_service_account_only() -> None:
    """The invariant is the principal kind, not one privileged role name.

    Two roles write silver and gold - ``pipeline`` and ``ingest_pipeline`` -
    and what makes that safe is that neither can be bound to a human, so no
    human path to those layers exists whatever bindings are seeded.
    """
    for layer in ("silver", "gold"):
        writers = roles_granting_write(layer)
        assert {role.code for role in writers} == {"pipeline", "ingest_pipeline"}, layer
        for role in writers:
            assert role.allowed_principal_kinds == frozenset({"service_account"}), role.code
    assert {role.code for role in roles_granting_write("raw")} == {"developer", "data_steward"}
    assert {role.code for role in roles_granting_write("bronze")} == {
        "developer",
        "data_steward",
        "pipeline",
        "ingest_pipeline",
    }


def test_pipeline_roles_are_service_account_only() -> None:
    for code in ("pipeline", "ingest_pipeline"):
        assert ROLES[code].allowed_principal_kinds == frozenset({"service_account"}), code
        with pytest.raises(PrincipalKindNotAllowed):
            validate_binding(code, "user", ScopeType.PROJECT)


def test_only_the_ingest_pipeline_creates_datasets_and_only_per_project() -> None:
    """Dataset creation is a governance act; plain pipeline stays out of it."""
    assert "dataset.create" not in ROLES["pipeline"].capabilities
    assert "dataset.create" in ROLES["ingest_pipeline"].capabilities
    assert ROLES["ingest_pipeline"].bindable_scopes == frozenset({ScopeType.PROJECT})
    validate_binding("ingest_pipeline", "service_account", ScopeType.PROJECT)
    for scope in (ScopeType.SYSTEM, ScopeType.ORGANIZATION, ScopeType.DATASET):
        with pytest.raises(ScopeNotBindable):
            validate_binding("ingest_pipeline", "service_account", scope)


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
