"""Scopes and grants of roles to LDAP groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.security.rbac.roles import Role, ScopeType, scope_type_of
from huron.pkg.errors import Invalid

if TYPE_CHECKING:
    import uuid

__all__ = ["PLATFORM", "Grant", "GrantInvalid", "Scope", "check_grant"]


@dataclass(frozen=True, slots=True, order=True)
class Scope:
    """The platform, one organization or one catalog."""

    type: ScopeType
    id: uuid.UUID | None = None

    @classmethod
    def organization(cls, organization_id: uuid.UUID) -> Scope:
        """The scope of one organization."""
        return cls(ScopeType.ORGANIZATION, organization_id)

    @classmethod
    def catalog(cls, catalog_id: uuid.UUID) -> Scope:
        """The scope of one catalog."""
        return cls(ScopeType.CATALOG, catalog_id)


PLATFORM = Scope(ScopeType.PLATFORM)


class GrantInvalid(Invalid):
    """A grant names a role at a scope it cannot be granted at."""


@dataclass(frozen=True, slots=True)
class Grant:
    """One role granted to one LDAP group at one scope."""

    scope: Scope
    role: Role
    ldap_group: str


def check_grant(grant: Grant) -> Grant:
    """Return ``grant`` when its role fits its scope; raises :class:`GrantInvalid`."""
    expected = scope_type_of(grant.role)
    if grant.scope.type is not expected:
        raise GrantInvalid(
            f"role {grant.role} is granted at {expected} scope",
            {"role": str(grant.role), "scope": str(grant.scope.type)},
        )
    if (grant.scope.type is ScopeType.PLATFORM) != (grant.scope.id is None):
        raise GrantInvalid("platform scope has no id; other scopes need one", {})
    if not grant.ldap_group or grant.ldap_group != grant.ldap_group.strip():
        raise GrantInvalid("LDAP group names are non-empty and unpadded", {})
    return grant
