"""Organizations."""

from __future__ import annotations

from fastapi import APIRouter, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.applications.api.routes.v1.schema.organizations import OrganizationIn, OrganizationOut
from huron.applications.api.routes.v1.schema.schemas import SchemaIn, SchemaOut

__all__ = ["router"]

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("")
async def list_organizations(
    actor: ActorDep, lake: LakeDep, cursor: Cursor = None, limit: Limit = None
) -> Page[OrganizationOut]:
    """Organizations the caller may see."""
    page = await lake.organizations.list(actor, cursor, limit)
    return page_of(OrganizationOut, [v.as_dict() for v in page.items], page.next_cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationIn, actor: ActorDep, lake: LakeDep
) -> OrganizationOut:
    """Create an organization; Platform Admin only."""
    view = await lake.organizations.create(actor, body.name, body.display_name, body.description)
    return OrganizationOut.model_validate(view.as_dict())


@router.get("/{organization}")
async def get_organization(organization: str, actor: ActorDep, lake: LakeDep) -> OrganizationOut:
    """One organization."""
    view = await lake.organizations.get(actor, organization)
    return OrganizationOut.model_validate(view.as_dict())


@router.delete("/{organization}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(organization: str, actor: ActorDep, lake: LakeDep) -> None:
    """Delete an organization that has no catalogs."""
    await lake.organizations.delete(actor, organization)


@router.get("/{organization}/schemas")
async def list_organization_schemas(
    organization: str, actor: ActorDep, lake: LakeDep, cursor: Cursor = None, limit: Limit = None
) -> Page[SchemaOut]:
    """Registry entries of the organization, by name and newest version first."""
    page = await lake.schemas.list(actor, organization, cursor, limit)
    return page_of(SchemaOut, [e.as_dict() for e in page.items], page.next_cursor)


@router.post("/{organization}/schemas", status_code=status.HTTP_201_CREATED)
async def publish_organization_schema(
    organization: str, body: SchemaIn, actor: ActorDep, lake: LakeDep
) -> SchemaOut:
    """Publish the next version of a named schema in the organization."""
    entry = await lake.schemas.publish(
        actor, organization, body.name, body.extends_id, body.document
    )
    return SchemaOut.model_validate(entry.as_dict())
