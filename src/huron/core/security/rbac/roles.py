"""The five fixed roles, their scopes and their privileges."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from huron.core.security.rbac.privileges import Privilege

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["CATALOG_ROLES", "ROLE_PRIVILEGES", "Role", "ScopeType", "scope_type_of"]


class ScopeType(StrEnum):
    """Where a grant applies."""

    PLATFORM = "platform"
    ORGANIZATION = "organization"
    CATALOG = "catalog"


class Role(StrEnum):
    """A fixed bundle of privileges granted to LDAP groups."""

    PLATFORM_ADMIN = "platform_admin"
    ORG_ADMIN = "org_admin"
    CATALOG_ADMIN = "catalog_admin"
    CONTRIBUTOR = "contributor"
    READER = "reader"


CATALOG_ROLES = (Role.CATALOG_ADMIN, Role.CONTRIBUTOR, Role.READER)

_P = Privilege
_READER = frozenset({_P.ORGANIZATION_READ, _P.CATALOG_READ, _P.COLLECTION_READ, _P.AUDIT_READ})
_CONTRIBUTOR = _READER | {
    _P.COLLECTION_CREATE,
    _P.COLLECTION_WRITE_METADATA,
    _P.COLLECTION_WRITE_FILES,
    _P.COLLECTION_DELETE_OWN,
}
_CATALOG_ADMIN = _CONTRIBUTOR | {
    _P.CATALOG_GRANT_MEMBER,
    _P.SCHEMA_ASSIGN,
    _P.NAMESPACE_CREATE,
    _P.NAMESPACE_DELETE,
    _P.NAMESPACE_CONFIGURE,
    _P.COLLECTION_DELETE_ANY,
}
_ORG_ADMIN = _CATALOG_ADMIN | {
    _P.CATALOG_CREATE,
    _P.CATALOG_DELETE,
    _P.CATALOG_GRANT_ADMIN,
    _P.SCHEMA_PUBLISH,
}
_PLATFORM_ADMIN = frozenset(Privilege)

ROLE_PRIVILEGES: Mapping[Role, frozenset[Privilege]] = {
    Role.PLATFORM_ADMIN: _PLATFORM_ADMIN,
    Role.ORG_ADMIN: _ORG_ADMIN,
    Role.CATALOG_ADMIN: _CATALOG_ADMIN,
    Role.CONTRIBUTOR: _CONTRIBUTOR,
    Role.READER: _READER,
}

_SCOPES: Mapping[Role, ScopeType] = {
    Role.PLATFORM_ADMIN: ScopeType.PLATFORM,
    Role.ORG_ADMIN: ScopeType.ORGANIZATION,
    Role.CATALOG_ADMIN: ScopeType.CATALOG,
    Role.CONTRIBUTOR: ScopeType.CATALOG,
    Role.READER: ScopeType.CATALOG,
}


def scope_type_of(role: Role) -> ScopeType:
    """The only scope type ``role`` may be granted at."""
    return _SCOPES[role]
