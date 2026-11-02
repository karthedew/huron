"""Organizations: the top of the hierarchy."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any

from huron.core.security.rbac import ORGANIZATION_ROLES, Role

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Iterator, Mapping
    from datetime import datetime

    from huron.core.lake.organizations.declarations import DeclaredOrganization

__all__ = ["Organization", "OrganizationGroups", "OrganizationView"]


@dataclass(frozen=True, slots=True)
class Organization:
    """An organization owns catalogs."""

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    version: int
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class OrganizationGroups:
    """The LDAP groups holding each organization-scope role, de-duplicated and sorted.

    ``org_admin`` administers the organization; ``catalog_admin``, ``contributor`` and ``reader``
    hold their role in every catalog of the organization, existing and future. A grant on one
    catalog adds to these and cannot remove them.
    """

    org_admin: tuple[str, ...] = ()
    catalog_admin: tuple[str, ...] = ()
    contributor: tuple[str, ...] = ()
    reader: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in fields(self):
            object.__setattr__(self, field.name, tuple(sorted(set(getattr(self, field.name)))))

    @classmethod
    def of(cls, granted: Mapping[Role, Iterable[str]]) -> OrganizationGroups:
        """The organization-scope groups among ``granted``; other roles are ignored."""
        return cls(**{role.value: tuple(granted.get(role, ())) for role in ORGANIZATION_ROLES})

    def groups(self, role: Role) -> tuple[str, ...]:
        """The groups holding ``role``; raises ``KeyError`` for a role not granted here."""
        if role not in ORGANIZATION_ROLES:
            raise KeyError(role)
        groups: tuple[str, ...] = getattr(self, role.value)
        return groups

    def items(self) -> Iterator[tuple[Role, tuple[str, ...]]]:
        """Every organization-scope role with its groups, Org Admin first."""
        for role in ORGANIZATION_ROLES:
            yield role, self.groups(role)

    def as_dict(self) -> dict[str, list[str]]:
        """Render as the API body of ``GET /organizations/{org}/grants``."""
        return {role.value: list(groups) for role, groups in self.items()}


@dataclass(frozen=True, slots=True)
class OrganizationView:
    """An organization as the API shows it, with its declaration when the configuration has one."""

    organization: Organization
    catalog_count: int
    declaration: DeclaredOrganization | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        organization = self.organization
        return {
            "id": str(organization.id),
            "name": organization.name,
            "display_name": organization.display_name,
            "description": organization.description,
            "version": organization.version,
            "created_at": organization.created_at.isoformat(),
            "created_by": organization.created_by,
            "catalog_count": self.catalog_count,
            **self._declared(),
        }

    def _declared(self) -> dict[str, Any]:
        if self.declaration is None:
            return {"declared": False, "root": None, "path": None, "export": None}
        return self.declaration.as_dict()
