"""Grants of roles to LDAP groups at platform, organization and catalog scope."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.v1.schema.grants import (
    GrantChangeOut,
    GrantSourceOut,
    GrantSourcesOut,
    GroupsIn,
    GroupsOut,
    OrganizationGroupsOut,
)
from huron.core.security.rbac import Role

__all__ = ["router"]

router = APIRouter(tags=["grants"])

CatalogRole = Literal["catalog_admin", "contributor", "reader"]
OrganizationRole = Literal["org_admin", "catalog_admin", "contributor", "reader"]


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
async def organization_grants(
    organization: str, actor: ActorDep, lake: LakeDep
) -> OrganizationGroupsOut:
    """Groups per organization-scope role; every catalog of the organization inherits them."""
    groups = await lake.grants.organization_groups(actor, organization)
    return OrganizationGroupsOut.model_validate(groups.as_dict())


@router.put("/organizations/{organization}/grants/{role}")
async def set_organization_grants(
    organization: str, role: OrganizationRole, body: GroupsIn, actor: ActorDep, lake: LakeDep
) -> GrantChangeOut:
    """Replace the groups of one organization-scope role of an undeclared organization."""
    change = await lake.grants.set_organization_role(
        actor, organization, Role(role), body.ldap_groups
    )
    return GrantChangeOut.model_validate(change.as_dict())


@router.get("/catalogs/{catalog}/grants/sources")
async def catalog_grant_sources(catalog: str, actor: ActorDep, lake: LakeDep) -> GrantSourcesOut:
    """Every grant holding on the catalog, with the scope it was made at."""
    sources = await lake.grants.catalog_grant_sources(actor, catalog)
    return GrantSourcesOut(
        items=[
            GrantSourceOut.model_validate(
                {"role": str(s.role), "group": s.ldap_group, "scope": str(s.scope.type)}
            )
            for s in sources
        ]
    )


@router.put("/catalogs/{catalog}/grants/{role}")
async def set_catalog_grants(
    catalog: str, role: CatalogRole, body: GroupsIn, actor: ActorDep, lake: LakeDep
) -> GrantChangeOut:
    """Replace the groups of a catalog role on the catalog; inherited groups stay."""
    change = await lake.grants.set_catalog_role(actor, catalog, Role(role), body.ldap_groups)
    return GrantChangeOut.model_validate(change.as_dict())
