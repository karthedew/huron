"""The role model: named capability bundles bound to principals at a scope.

This module is the single source of truth for the platform's roles. The
Alembic seed (``migrations/versions/0002_rbac.py``) and the API's role
endpoints both derive from ``ROLES``; a unit test asserts the invariants that
matter operationally:

- every role holding ``data.write`` on the silver or gold layer is bindable
  only to service accounts (``pipeline`` and ``ingest_pipeline``). The
  invariant is the principal kind, not one privileged role name.
- only ``ingest_pipeline`` pairs ``dataset.create`` with those writes, and it
  binds at project scope alone.
- administrative roles (``organization_admin``, ``platform_owner``) carry no
  ``data.write`` at all: administration and data production are separate
  concerns.

Roles compile to the plain capability :class:`~huron.pkg.rbac.Binding`
values the pure ``decide()`` engine evaluates, so enforcement stays in one
place and the role layer is only vocabulary plus validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.pkg.rbac import Binding, Effect, ScopeType

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

PRINCIPAL_KIND_USER = "user"
PRINCIPAL_KIND_SERVICE_ACCOUNT = "service_account"
PRINCIPAL_KINDS = frozenset({PRINCIPAL_KIND_USER, PRINCIPAL_KIND_SERVICE_ACCOUNT})

DATA_LAYERS = ("raw", "bronze", "silver", "gold")

#: Capabilities that ever carry a non-NULL ``layers`` restriction on a role
#: binding. ``layers=NULL`` in ``role_capabilities`` already means "every
#: layer", so the presence of the column can't distinguish a layered
#: capability from a control-plane one on its own - this is the accompanying
#: fact, and every consumer of ``role_capabilities`` (or its Postgres mirror)
#: needs it to split a role's rows into a control-plane binding plus one
#: binding per layer grant.
LAYER_SCOPED_CAPABILITIES: frozenset[str] = frozenset({"data.read", "data.write"})

#: Every control-plane capability the platform knows. Layer-scoped data-plane
#: capabilities are ``data.read`` and ``data.write``; the layer travels as a
#: separate argument to ``decide()`` and as ``Binding.layers``.
CAPABILITIES: frozenset[str] = frozenset(
    {
        "organization.create",
        "organization.update",
        "organization.delete",
        "organization.policy_attach",
        "project.create",
        "project.update",
        "project.policy_attach",
        "dataset.create",
        "dataset.update",
        "dataset.policy_attach",
        "dataset.discover",
        "release.create",
        "rbac.binding_manage",
        "service_account.manage",
        "user.manage",
        "data.read",
        "data.write",
    }
)


class RoleError(Exception):
    """A role lookup or role binding violated the role model."""

    code = "ROLE_VIOLATION"


class UnknownRole(RoleError):
    code = "UNKNOWN_ROLE"


class PrincipalKindNotAllowed(RoleError):
    """The role restricts which kind of principal may hold it."""

    code = "PRINCIPAL_KIND_NOT_ALLOWED"


class ScopeNotBindable(RoleError):
    """The role cannot be granted at the requested scope level."""

    code = "SCOPE_NOT_BINDABLE"


@dataclass(frozen=True, slots=True)
class LayerGrant:
    """A data-plane capability limited to a set of storage layers.

    ``layers=None`` means every layer, mirroring ``Binding.layers``.
    """

    capability: str
    layers: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    code: str
    title: str
    #: Control-plane capabilities (no layer dimension).
    capabilities: frozenset[str]
    #: Layer-scoped data-plane grants; compiled to their own bindings.
    layer_grants: tuple[LayerGrant, ...]
    #: Scope levels a binding for this role may be created at.
    bindable_scopes: frozenset[ScopeType]
    #: Principal kinds that may hold this role (the Silver/Gold invariant).
    allowed_principal_kinds: frozenset[str]
    description: str = ""

    def grants_write(self, layer: str) -> bool:
        return any(
            grant.capability == "data.write" and (grant.layers is None or layer in grant.layers)
            for grant in self.layer_grants
        )


_ANY_KIND = PRINCIPAL_KINDS
_HUMAN_SCOPES = frozenset({ScopeType.ORGANIZATION, ScopeType.PROJECT, ScopeType.DATASET})

ROLES: dict[str, RoleDefinition] = {
    role.code: role
    for role in (
        RoleDefinition(
            code="reader",
            title="Reader",
            capabilities=frozenset({"dataset.discover"}),
            layer_grants=(LayerGrant("data.read"),),
            bindable_scopes=_HUMAN_SCOPES,
            allowed_principal_kinds=_ANY_KIND,
            description="Discover datasets and read every layer in scope.",
        ),
        RoleDefinition(
            code="developer",
            title="Developer",
            capabilities=frozenset(
                {"dataset.discover", "dataset.create", "dataset.update", "release.create"}
            ),
            layer_grants=(
                LayerGrant("data.read"),
                LayerGrant("data.write", frozenset({"raw", "bronze"})),
            ),
            bindable_scopes=_HUMAN_SCOPES,
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
            description="Commit to raw and bronze; create and tag datasets.",
        ),
        RoleDefinition(
            code="data_steward",
            title="Data Steward",
            capabilities=frozenset(
                {
                    "dataset.discover",
                    "dataset.create",
                    "dataset.update",
                    "dataset.policy_attach",
                    "release.create",
                }
            ),
            layer_grants=(
                LayerGrant("data.read"),
                LayerGrant("data.write", frozenset({"raw", "bronze"})),
            ),
            bindable_scopes=_HUMAN_SCOPES,
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
            description=(
                "Everything a developer does, plus dataset policy. Stewards shape "
                "silver/gold by configuring pipelines - they never hold the write."
            ),
        ),
        RoleDefinition(
            code="project_admin",
            title="Project Admin",
            capabilities=frozenset(
                {
                    "dataset.discover",
                    "project.update",
                    "project.policy_attach",
                    "dataset.create",
                    "dataset.update",
                    "dataset.policy_attach",
                    "release.create",
                    "rbac.binding_manage",
                }
            ),
            layer_grants=(LayerGrant("data.read"),),
            bindable_scopes=frozenset({ScopeType.ORGANIZATION, ScopeType.PROJECT}),
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
            description="Administer projects and their bindings; no data writes.",
        ),
        RoleDefinition(
            code="organization_admin",
            title="Organization Admin",
            capabilities=frozenset(
                {
                    "dataset.discover",
                    "organization.update",
                    "organization.policy_attach",
                    "project.create",
                    "project.update",
                    "project.policy_attach",
                    "dataset.policy_attach",
                    "service_account.manage",
                    "rbac.binding_manage",
                }
            ),
            layer_grants=(LayerGrant("data.read"),),
            bindable_scopes=frozenset({ScopeType.ORGANIZATION}),
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
            description="Administer one organization, its service accounts and bindings.",
        ),
        RoleDefinition(
            code="platform_owner",
            title="Platform Owner",
            capabilities=frozenset(
                {
                    "organization.create",
                    "organization.update",
                    "organization.delete",
                    "organization.policy_attach",
                    "project.create",
                    "project.update",
                    "project.policy_attach",
                    "dataset.create",
                    "dataset.update",
                    "dataset.policy_attach",
                    "dataset.discover",
                    "release.create",
                    "service_account.manage",
                    "rbac.binding_manage",
                    "user.manage",
                }
            ),
            layer_grants=(LayerGrant("data.read"),),
            bindable_scopes=frozenset({ScopeType.SYSTEM}),
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
            description="Platform-wide administration. Deliberately no data.write.",
        ),
        RoleDefinition(
            code="pipeline",
            title="Pipeline",
            capabilities=frozenset({"dataset.discover"}),
            layer_grants=(
                LayerGrant("data.read"),
                LayerGrant("data.write", frozenset({"bronze", "silver", "gold"})),
            ),
            bindable_scopes=frozenset({ScopeType.PROJECT, ScopeType.DATASET}),
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_SERVICE_ACCOUNT}),
            description=(
                "Writes bronze, silver and gold for datasets that already exist. "
                "Holdable exclusively by service accounts, which only organization "
                "admins may create."
            ),
        ),
        RoleDefinition(
            code="ingest_pipeline",
            title="Ingest Pipeline",
            capabilities=frozenset({"dataset.discover", "dataset.create"}),
            layer_grants=(
                LayerGrant("data.read"),
                LayerGrant("data.write", frozenset({"bronze", "silver", "gold"})),
            ),
            bindable_scopes=frozenset({ScopeType.PROJECT}),
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_SERVICE_ACCOUNT}),
            description=(
                "A pipeline whose data originates outside the lake - a streaming feed, "
                "an instrument, an external service - and which therefore has to mint "
                "the dataset it is about to fill. Project scope only, so a feed creates "
                "datasets in exactly the project it was granted. Prefer plain "
                "'pipeline': dataset creation is a governance act (classification, "
                "retention, declared contract), so the default is that a human creates "
                "and configures the dataset and the pipeline only writes into it."
            ),
        ),
    )
}


def role(code: str) -> RoleDefinition:
    try:
        return ROLES[code]
    except KeyError as exc:
        raise UnknownRole(f"unknown role: {code}") from exc


def validate_binding(role_code: str, principal_kind: str, scope_type: ScopeType) -> RoleDefinition:
    """Check a proposed binding against the role model; return the role."""
    definition = role(role_code)
    if principal_kind not in PRINCIPAL_KINDS:
        raise PrincipalKindNotAllowed(f"unknown principal kind: {principal_kind}")
    if principal_kind not in definition.allowed_principal_kinds:
        raise PrincipalKindNotAllowed(
            f"role {role_code} may not be held by a {principal_kind} principal"
        )
    if scope_type not in definition.bindable_scopes:
        raise ScopeNotBindable(f"role {role_code} cannot be bound at {scope_type.value} scope")
    return definition


def compile_binding(
    role_code: str,
    *,
    principal_identifier: str,
    principal_kind: str,
    scope_type: ScopeType,
    scope_id: UUID | None,
    expires_at: datetime | None = None,
) -> tuple[Binding, ...]:
    """Expand one role grant into the capability bindings ``decide()`` reads.

    A role becomes one binding for its control-plane capabilities plus one
    binding per layer grant, so a role can read every layer while writing
    only some.
    """
    definition = validate_binding(role_code, principal_kind, scope_type)
    compiled: list[Binding] = []
    if definition.capabilities:
        compiled.append(
            Binding(
                principal=principal_identifier,
                capabilities=definition.capabilities,
                scope_type=scope_type,
                scope_id=scope_id,
                effect=Effect.ALLOW,
                expires_at=expires_at,
            )
        )
    compiled.extend(
        Binding(
            principal=principal_identifier,
            capabilities=frozenset({grant.capability}),
            scope_type=scope_type,
            scope_id=scope_id,
            effect=Effect.ALLOW,
            expires_at=expires_at,
            layers=grant.layers,
        )
        for grant in definition.layer_grants
    )
    return tuple(compiled)


def roles_granting_write(layer: str) -> tuple[RoleDefinition, ...]:
    """The roles whose bindings can allow ``data.write`` on ``layer``."""
    return tuple(definition for definition in ROLES.values() if definition.grants_write(layer))


__all__ = [
    "CAPABILITIES",
    "DATA_LAYERS",
    "LAYER_SCOPED_CAPABILITIES",
    "PRINCIPAL_KINDS",
    "PRINCIPAL_KIND_SERVICE_ACCOUNT",
    "PRINCIPAL_KIND_USER",
    "ROLES",
    "LayerGrant",
    "PrincipalKindNotAllowed",
    "RoleDefinition",
    "RoleError",
    "ScopeNotBindable",
    "UnknownRole",
    "compile_binding",
    "role",
    "roles_granting_write",
    "validate_binding",
]
