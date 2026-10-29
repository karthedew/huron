"""Grants of roles to LDAP groups at platform, organization and catalog scope."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.v1.schema.grants import (
    EffectiveGroupsOut,
    GrantChangeOut,
    GroupsIn,
    GroupsOut,
)
from huron.core.security.rbac import Role

__all__ = ["router"]

router = APIRouter(tags=["grants"])

CatalogRole = Literal["catalog_admin", "contributor", "reader"]


@router.get("/platform/grants")
async def platform_grants(actor: ActorDep, lake: LakeDep) -> GroupsOut:
    """Groups holding Platform Admin."""
    groups = await lake.grants.platform_admins(actor)
    return GroupsOut(role=str(Role.PLATFORM_ADMIN), ldap_groups=groups)


@router.put("/platform/grants/platform_admin")
async def set_platform_grants(body: GroupsIn, actor: ActorDep, lake: LakeDep) -> GrantChangeOut:
    """Replace the Platform Admin groups; the configured group always stays."""
    change = await lake.grants.set_platform_admins(actor, body.ldap_groups)
    return GrantChangeOut.model_validate(change.as_dict())


@router.get("/organizations/{organization}/grants")
async def organization_grants(organization: str, actor: ActorDep, lake: LakeDep) -> GroupsOut:
    """Groups holding Org Admin on the organization."""
    groups = await lake.grants.org_admins(actor, organization)
    return GroupsOut(role=str(Role.ORG_ADMIN), ldap_groups=groups)


@router.put("/organizations/{organization}/grants/org_admin")
async def set_organization_grants(
    organization: str, body: GroupsIn, actor: ActorDep, lake: LakeDep
) -> GrantChangeOut:
    """Replace the Org Admin groups of the organization."""
    change = await lake.grants.set_org_admins(actor, organization, body.ldap_groups)
    return GrantChangeOut.model_validate(change.as_dict())


@router.get("/catalogs/{catalog}/grants")
async def catalog_grants(catalog: str, actor: ActorDep, lake: LakeDep) -> EffectiveGroupsOut:
    """Effective groups per role on the catalog, inherited ones included."""
    groups = await lake.grants.catalog_groups(actor, catalog)
    return EffectiveGroupsOut.model_validate(groups.as_dict())


@router.put("/catalogs/{catalog}/grants/{role}")
async def set_catalog_grants(
    catalog: str, role: CatalogRole, body: GroupsIn, actor: ActorDep, lake: LakeDep
) -> GrantChangeOut:
    """Replace the groups of a catalog role."""
    change = await lake.grants.set_catalog_role(actor, catalog, Role(role), body.ldap_groups)
    return GrantChangeOut.model_validate(change.as_dict())
