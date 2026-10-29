"""Grant bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["EffectiveGroupsOut", "GrantChangeOut", "GroupsIn", "GroupsOut"]


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


class EffectiveGroupsOut(BaseModel):
    """Groups per role on a catalog, inherited ones included."""

    platform_admin: list[str]
    org_admin: list[str]
    catalog_admin: list[str]
    contributor: list[str]
    reader: list[str]
