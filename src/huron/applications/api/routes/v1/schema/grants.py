"""Grant bodies."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "GrantChangeOut",
    "GrantSourceOut",
    "GrantSourcesOut",
    "GroupsIn",
    "GroupsOut",
    "OrganizationGroupsOut",
]


class GroupsIn(BaseModel):
    """The complete set of LDAP groups for one role."""

    ldap_groups: list[str] = Field(max_length=200)


class GroupsOut(BaseModel):
    """The LDAP groups holding one role."""

    role: str
    ldap_groups: list[str]


class GrantChangeOut(BaseModel):
    """The result of replacing a role's groups."""

    role: str
    ldap_groups: list[str]
    added: list[str]
    removed: list[str]


class OrganizationGroupsOut(BaseModel):
    """Groups per organization-scope role.

    ``catalog_admin``, ``contributor`` and ``reader`` hold their role in every catalog of the
    organization.
    """

    org_admin: list[str]
    catalog_admin: list[str]
    contributor: list[str]
    reader: list[str]


class GrantSourceOut(BaseModel):
    """One group holding one role on a catalog, and the scope the grant was made at."""

    role: Literal["platform_admin", "org_admin", "catalog_admin", "contributor", "reader"]
    group: str
    scope: Literal["platform", "organization", "catalog"]


class GrantSourcesOut(BaseModel):
    """Every grant holding on a catalog, sorted by role (Platform Admin first), group, scope."""

    items: list[GrantSourceOut]
