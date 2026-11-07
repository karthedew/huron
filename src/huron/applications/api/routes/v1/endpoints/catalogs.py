"""Catalogs, their schema assignment and their audit log."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Query, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import (
    DeclarationsDep,
    DiskDep,
    LakeDep,
    with_share_root,
)
from huron.applications.api.routes.pagination import Cursor, Limit, Order, Sort
from huron.applications.api.routes.v1.schema.admin import AuditOut
from huron.applications.api.routes.v1.schema.catalogs import (
    AssignIn,
    AssignOut,
    CatalogIn,
    CatalogOut,
    CatalogWriteOut,
    RecomputeOut,
    ShareGroupIn,
)
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.core.lake.listing import ListOrder, SortDirection, SortField

if TYPE_CHECKING:
    from huron.core.lake.catalogs.models import CatalogView
    from huron.core.lake.organizations.declarations import Declarations
    from huron.core.storage import ShareWarning

__all__ = ["router"]

router = APIRouter(tags=["catalogs"])


@router.get("/catalogs")
async def list_catalogs(
    actor: ActorDep,
    lake: LakeDep,
    declarations: DeclarationsDep,
    organization: Annotated[str | None, Query()] = None,
    cursor: Cursor = None,
    limit: Limit = None,
    sort: Sort = SortField.NAME,
    order: Order = SortDirection.ASC,
) -> Page[CatalogOut]:
    """Catalogs the caller may see, optionally within one organization."""
    page = await lake.catalogs.list(actor, organization, cursor, limit, ListOrder(sort, order))
    rows = [with_share_root(v.as_dict(), declarations) for v in page.items]
    return page_of(CatalogOut, rows, page.next_cursor)


@router.post("/organizations/{organization}/catalogs", status_code=status.HTTP_201_CREATED)
async def create_catalog(
    organization: str,
    body: CatalogIn,
    actor: ActorDep,
    lake: LakeDep,
    declarations: DeclarationsDep,
    disk: DiskDep,
) -> CatalogWriteOut:
    """Create a catalog in an organization; the default schema is the latest huron-base.

    With a share group and a lake, the API then tries to give the directory that group.
    """
    view = await lake.catalogs.create(
        actor,
        organization,
        body.name,
        body.display_name,
        body.description,
        body.schema_id,
        share_group=body.share_group,
    )
    warning = None
    if disk is not None and body.share_group is not None:
        warning = await disk.set_share_group(view.disk_path, body.share_group)
    return _written(view, declarations, warning)


@router.get("/catalogs/{catalog}")
async def get_catalog(
    catalog: str, actor: ActorDep, lake: LakeDep, declarations: DeclarationsDep
) -> CatalogOut:
    """One catalog."""
    view = await lake.catalogs.get(actor, catalog)
    return CatalogOut.model_validate(with_share_root(view.as_dict(), declarations))


@router.patch("/catalogs/{catalog}")
async def set_catalog_share_group(
    catalog: str,
    body: ShareGroupIn,
    actor: ActorDep,
    lake: LakeDep,
    declarations: DeclarationsDep,
    disk: DiskDep,
) -> CatalogWriteOut:
    """Set or clear the catalog's share group; the catalog lock orders the changes.

    With a lake, the API then tries to give the directory the share group, or the service group
    when the share group is cleared.
    """
    view = await lake.catalogs.set_share_group(actor, catalog, body.share_group)
    warning = None
    if disk is not None:
        warning = await disk.set_share_group(view.disk_path, view.catalog.share_group)
    return _written(view, declarations, warning)


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
    catalog: str,
    body: AssignIn,
    actor: ActorDep,
    lake: LakeDep,
    declarations: DeclarationsDep,
) -> AssignOut:
    """Assign a registry entry and re-validate the catalog's settled collections."""
    view, result = await lake.catalogs.assign_schema(actor, catalog, body.schema_id)
    return AssignOut(
        assigned=CatalogOut.model_validate(with_share_root(view.as_dict(), declarations)),
        recompute=RecomputeOut.model_validate(result.as_dict()),
    )


@router.get("/catalogs/{catalog}/log")
async def catalog_log(
    catalog: str, actor: ActorDep, lake: LakeDep, cursor: Cursor = None, limit: Limit = None
) -> Page[AuditOut]:
    """Audit entries within the catalog, newest first."""
    page = await lake.audit.for_catalog(actor, catalog, cursor, limit)
    return page_of(AuditOut, [e.as_dict() for e in page.items], page.next_cursor)


def _written(
    view: CatalogView, declarations: Declarations, warning: ShareWarning | None
) -> CatalogWriteOut:
    warnings = [] if warning is None else [asdict(warning)]
    row = with_share_root(view.as_dict(), declarations)
    return CatalogWriteOut.model_validate({**row, "warnings": warnings})
