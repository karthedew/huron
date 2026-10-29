"""Namespaces within a catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.applications.api.routes.v1.schema.namespaces import (
    NamespaceConfigureIn,
    NamespaceIn,
    NamespaceOut,
)

__all__ = ["router"]

router = APIRouter(prefix="/catalogs/{catalog}/namespaces", tags=["namespaces"])


@router.get("")
async def list_namespaces(
    catalog: str,
    actor: ActorDep,
    lake: LakeDep,
    parent: Annotated[str, Query(description="Dotted parent path; empty for the root.")] = "",
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[NamespaceOut]:
    """Direct children of ``parent``."""
    page = await lake.namespaces.children(actor, catalog, parent, cursor, limit)
    return page_of(NamespaceOut, [v.as_dict() for v in page.items], page.next_cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_namespace(
    catalog: str, body: NamespaceIn, actor: ActorDep, lake: LakeDep
) -> NamespaceOut:
    """Create a namespace; the parent must exist."""
    view = await lake.namespaces.create(
        actor, catalog, body.parent, body.name, body.collections_allowed
    )
    return NamespaceOut.model_validate(view.as_dict())


@router.get("/{path}")
async def get_namespace(catalog: str, path: str, actor: ActorDep, lake: LakeDep) -> NamespaceOut:
    """One namespace by dotted path."""
    view = await lake.namespaces.get(actor, catalog, path)
    return NamespaceOut.model_validate(view.as_dict())


@router.patch("/{path}")
async def configure_namespace(
    catalog: str, path: str, body: NamespaceConfigureIn, actor: ActorDep, lake: LakeDep
) -> NamespaceOut:
    """Allow or forbid collections in the namespace."""
    view = await lake.namespaces.configure(actor, catalog, path, body.collections_allowed)
    return NamespaceOut.model_validate(view.as_dict())


@router.delete("/{path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_namespace(catalog: str, path: str, actor: ActorDep, lake: LakeDep) -> None:
    """Delete an empty namespace."""
    await lake.namespaces.delete(actor, catalog, path)
