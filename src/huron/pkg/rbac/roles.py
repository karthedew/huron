"""The role model: named capability bundles bound to principals at a scope.

This module is the single source of truth for the platform's roles. The
Alembic seed (``migrations/versions/0002_rbac.py``) and the API's role
endpoints both derive from ``ROLES``; a unit test asserts the invariants that
matter operationally:

- no role in the vocabulary carries ``data.write`` on silver or gold, and
  every role is holdable by human (``user``) principals only. Service
  accounts hold no roles at all: their single authority - dataset CRUD plus
  silver/gold read/write across their owning organization - is intrinsic to
  the principal kind and synthesized by :func:`service_account_bindings`,
  never granted through a binding. Silver/gold writers are therefore
  service accounts by construction (invariant J).
- administrative roles (``organization_admin``, ``platform_owner``) carry no
  ``data.write`` at all: administration and data production are separate
  concerns.

Roles compile to the plain capability :class:`~huron.pkg.rbac.Binding`
values the pure ``decide()`` engine evaluates, so enforcement stays in one
place and the role layer is only vocabulary plus validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from huron.pkg.rbac import Binding, Effect, ScopeType

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

PRINCIPAL_KIND_USER = "user"
PRINCIPAL_KIND_SERVICE_ACCOUNT = "service_account"
PRINCIPAL_KINDS = frozenset({PRINCIPAL_KIND_USER, PRINCIPAL_KIND_SERVICE_ACCOUNT})

DATA_LAYERS = ("raw", "bronze", "silver", "gold")

#: The layers a service account's intrinsic authority reaches. Raw and bronze
#: are the human contribution surface; an organization's service accounts
#: exist to produce and maintain its silver and gold representations.
SERVICE_ACCOUNT_LAYERS: frozenset[str] = frozenset({"silver", "gold"})

#: The control-plane half of that authority: a feed may mint the dataset it
#: is about to fill (direct entry) and maintain its descriptive state, under
#: the same inherited policies as a human creation.
SERVICE_ACCOUNT_CAPABILITIES: frozenset[str] = frozenset(
    {"dataset.create", "dataset.update", "dataset.discover"}
)

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
    """A role lookup or role binding violated the role model.

    Abstract: every subclass names a stable ``code`` of its own and none
    overrides it per instance, so unlike ``DomainError`` it is a true
    ``ClassVar`` here.
    """

    code: ClassVar[str]


class UnknownRole(RoleError):
    """The ``UNKNOWN_ROLE`` condition: the code names no role in ``ROLES``.

    Raised by :func:`role`, and so by anything that validates or compiles
    a binding for a role code that was never defined.
    """

    code = "UNKNOWN_ROLE"


class PrincipalKindNotAllowed(RoleError):
    """The role restricts which kind of principal may hold it.

    The ``PRINCIPAL_KIND_NOT_ALLOWED`` condition. :func:`validate_binding`
    raises it in three cases: a principal kind outside ``PRINCIPAL_KINDS``,
    a service account (which holds no roles at all), and a kind the role's
    ``allowed_principal_kinds`` excludes.
    """

    code = "PRINCIPAL_KIND_NOT_ALLOWED"


class ScopeNotBindable(RoleError):
    """The role cannot be granted at the requested scope level.

    The ``SCOPE_NOT_BINDABLE`` condition: the scope type is outside the
    role's ``bindable_scopes`` - a ``platform_owner`` anywhere but
    ``SYSTEM``, an ``organization_admin`` below its organization, and so on.
    """

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
    """One named role: the capabilities it bundles and the rules for binding it.

    A definition is vocabulary, not enforcement: :func:`compile_binding`
    turns it into plain bindings and ``decide()`` never sees the role.
    ``code`` is the stable identifier a binding row and the API carry;
    ``title`` and ``description`` are what the API shows for it.
    """

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
        """Return whether a binding for this role can allow ``data.write`` on ``layer``.

        True when some layer grant carries ``data.write`` and either names
        ``layer`` or is unrestricted (``layers=None``).

        Args:
            layer: A storage layer code from ``DATA_LAYERS``.

        Returns:
            True when the role writes to that layer.
        """
        return any(
            grant.capability == "data.write" and (grant.layers is None or layer in grant.layers)
            for grant in self.layer_grants
        )


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
            allowed_principal_kinds=frozenset({PRINCIPAL_KIND_USER}),
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
    )
}


def role(code: str) -> RoleDefinition:
    """Look up a role definition by its stable code.

    Args:
        code: A role code such as ``developer``.

    Returns:
        The definition registered in ``ROLES`` under ``code``.

    Raises:
        UnknownRole: If no role has that code.
    """
    try:
        return ROLES[code]
    except KeyError as exc:
        raise UnknownRole(f"unknown role: {code}") from exc


def validate_binding(role_code: str, principal_kind: str, scope_type: ScopeType) -> RoleDefinition:
    """Check a proposed binding against the role model; return the role.

    The checks run in order: the role must exist (an unknown code fails in
    :func:`role` with ``UnknownRole``); the principal kind must be one of
    ``PRINCIPAL_KINDS``; it must not be a service account, which holds no
    roles because its authority is intrinsic to the kind; it must be a kind
    the role allows; and the scope type must be one the role can be bound
    at. Stores run this before writing a binding, so an invalid grant is
    refused before any row exists.

    Args:
        role_code: The role being granted.
        principal_kind: ``user`` or ``service_account``.
        scope_type: The level the binding would attach at.

    Returns:
        The role's definition, ready to compile.

    Raises:
        PrincipalKindNotAllowed: If the kind is unknown, is a service
            account, or is not one the role allows.
        ScopeNotBindable: If the role is not bindable at ``scope_type``.
    """
    definition = role(role_code)
    if principal_kind not in PRINCIPAL_KINDS:
        raise PrincipalKindNotAllowed(f"unknown principal kind: {principal_kind}")
    if principal_kind == PRINCIPAL_KIND_SERVICE_ACCOUNT:
        raise PrincipalKindNotAllowed(
            "service accounts hold no roles; their authority is intrinsic to the principal kind"
        )
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
    only some. Every binding produced is an ``ALLOW`` sharing the same
    principal, scope and expiry; the control-plane binding is omitted for
    a role with no control-plane capabilities. The grant is validated
    first, so the ``RoleError`` subclasses of :func:`validate_binding`
    surface from here unchanged.

    Args:
        role_code: The role being granted.
        principal_identifier: The ``user:``, ``sa:`` or ``group:`` string
            the bindings address.
        principal_kind: ``user`` or ``service_account``; checked against
            the role, not derived from the identifier.
        scope_type: The level the bindings attach at.
        scope_id: The organization, project or dataset id, or None for
            ``SYSTEM``.
        expires_at: When every produced binding stops applying, or None
            for no expiry.

    Returns:
        The compiled bindings: the control-plane binding first, when the
        role has one, then one per layer grant in definition order.
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
    """Return the roles whose bindings can allow ``data.write`` on ``layer``.

    This is the operational check behind the invariant that no role writes
    silver or gold: for those layers it returns nothing.

    Args:
        layer: A storage layer code from ``DATA_LAYERS``.

    Returns:
        The matching definitions in ``ROLES`` order; empty when no role
        writes there.
    """
    return tuple(definition for definition in ROLES.values() if definition.grants_write(layer))


def service_account_bindings(
    principal_identifier: str, organization_id: UUID
) -> tuple[Binding, ...]:
    """Synthesize the whole of a service account's authority.

    A service account holds no roles and appears in no binding row; what it
    may do is a fixed property of the principal kind, scoped to the one
    organization that owns it: create, update and discover datasets, and
    read/write their silver and gold representations. Conferred in whole
    when an organization admin creates the account, revoked in whole with
    the account or its keys - never widened, narrowed, or reshaped through
    the role system.

    Args:
        principal_identifier: The account's ``sa:{subject}`` identifier.
        organization_id: The one organization that owns the account and
            bounds everything it may do.

    Returns:
        Three never-expiring ``ALLOW`` bindings at the organization's
        scope: ``SERVICE_ACCOUNT_CAPABILITIES``, then ``data.read`` and
        ``data.write`` each restricted to ``SERVICE_ACCOUNT_LAYERS``.
    """
    return (
        Binding(
            principal=principal_identifier,
            capabilities=SERVICE_ACCOUNT_CAPABILITIES,
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
            effect=Effect.ALLOW,
        ),
        Binding(
            principal=principal_identifier,
            capabilities=frozenset({"data.read"}),
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
            effect=Effect.ALLOW,
            layers=SERVICE_ACCOUNT_LAYERS,
        ),
        Binding(
            principal=principal_identifier,
            capabilities=frozenset({"data.write"}),
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
            effect=Effect.ALLOW,
            layers=SERVICE_ACCOUNT_LAYERS,
        ),
    )


__all__ = [
    "CAPABILITIES",
    "DATA_LAYERS",
    "LAYER_SCOPED_CAPABILITIES",
    "PRINCIPAL_KINDS",
    "PRINCIPAL_KIND_SERVICE_ACCOUNT",
    "PRINCIPAL_KIND_USER",
    "ROLES",
    "SERVICE_ACCOUNT_CAPABILITIES",
    "SERVICE_ACCOUNT_LAYERS",
    "LayerGrant",
    "PrincipalKindNotAllowed",
    "RoleDefinition",
    "RoleError",
    "ScopeNotBindable",
    "UnknownRole",
    "compile_binding",
    "role",
    "roles_granting_write",
    "service_account_bindings",
    "validate_binding",
]
