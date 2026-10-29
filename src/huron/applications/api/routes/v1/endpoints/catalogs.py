"""Catalogs, their schema assignment and their audit log."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.v1.schema.admin import AuditOut
from huron.applications.api.routes.v1.schema.catalogs import (
    AssignIn,
    AssignOut,
    CatalogIn,
    CatalogOut,
    RecomputeOut,
)
from huron.applications.api.routes.v1.schema.common import Page, page_of

__all__ = ["router"]

router = APIRouter(tags=["catalogs"])


@router.get("/catalogs")
async def list_catalogs(
    actor: ActorDep,
    lake: LakeDep,
    organization: Annotated[str | None, Query()] = None,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[CatalogOut]:
    """Catalogs the caller may see, optionally within one organization."""
    page = await lake.catalogs.list(actor, organization, cursor, limit)
    return page_of(CatalogOut, [v.as_dict() for v in page.items], page.next_cursor)


@router.post("/organizations/{organization}/catalogs", status_code=status.HTTP_201_CREATED)
async def create_catalog(
    organization: str, body: CatalogIn, actor: ActorDep, lake: LakeDep
) -> CatalogOut:
    """Create a catalog in an organization; the default schema is the latest huron-base."""
    view = await lake.catalogs.create(
        actor, organization, body.name, body.display_name, body.description, body.schema_id
    )
    return CatalogOut.model_validate(view.as_dict())


@router.get("/catalogs/{catalog}")
async def get_catalog(catalog: str, actor: ActorDep, lake: LakeDep) -> CatalogOut:
    """One catalog."""
    return CatalogOut.model_validate((await lake.catalogs.get(actor, catalog)).as_dict())


@router.delete("/catalogs/{catalog}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog(catalog: str, actor: ActorDep, lake: LakeDep) -> None:
    """Delete a catalog that has no namespaces."""
    await lake.catalogs.delete(actor, catalog)


@router.get("/catalogs/{catalog}/schema")
async def get_catalog_schema(catalog: str, actor: ActorDep, lake: LakeDep) -> dict[str, Any]:
    """The catalog's resolved schema document."""
    return await lake.catalogs.resolved_schema(actor, catalog)


@router.put("/catalogs/{catalog}/schema")
async def assign_catalog_schema(
    catalog: str, body: AssignIn, actor: ActorDep, lake: LakeDep
) -> AssignOut:
    """Assign a registry entry and re-validate the catalog's settled collections."""
    view, result = await lake.catalogs.assign_schema(actor, catalog, body.schema_id)
    return AssignOut(
        assigned=CatalogOut.model_validate(view.as_dict()),
        recompute=RecomputeOut.model_validate(result.as_dict()),
    )


@router.get("/catalogs/{catalog}/log")
async def catalog_log(
    catalog: str, actor: ActorDep, lake: LakeDep, cursor: Cursor = None, limit: Limit = None
) -> Page[AuditOut]:
    """Audit entries within the catalog, newest first."""
    page = await lake.audit.for_catalog(actor, catalog, cursor, limit)
    return page_of(AuditOut, [e.as_dict() for e in page.items], page.next_cursor)
