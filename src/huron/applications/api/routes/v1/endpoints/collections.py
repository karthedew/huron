"""Collections: drafts, metadata, activation, reads, search and deletion."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.preconditions import IfMatch, expected_version, set_etag
from huron.applications.api.routes.v1.schema.admin import AuditOut
from huron.applications.api.routes.v1.schema.collections import (
    CollectionIn,
    CollectionOut,
    CollectionPatch,
)
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.core.lake.collections.models import UNSET, CollectionView, Search, State, Update
from huron.pkg.errors import Invalid

__all__ = ["router"]

router = APIRouter(tags=["collections"])


@router.get("/catalogs/{catalog}/namespaces/{path}/collections")
async def list_collections(
    catalog: str,
    path: str,
    actor: ActorDep,
    lake: LakeDep,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[CollectionOut]:
    """Collections directly in a namespace; drafts only for those who may create them."""
    page = await lake.collections.list(actor, catalog, path, cursor, limit)
    return page_of(CollectionOut, [v.as_dict() for v in page.items], page.next_cursor)


@router.post(
    "/catalogs/{catalog}/namespaces/{path}/collections", status_code=status.HTTP_201_CREATED
)
async def create_collection(
    catalog: str,
    path: str,
    body: CollectionIn,
    actor: ActorDep,
    lake: LakeDep,
    response: Response,
) -> CollectionOut:
    """Reserve a draft collection in a namespace that allows collections."""
    view = await lake.collections.create(actor, catalog, path, body.name, body.metadata)
    return _out(view, response)


@router.get("/catalogs/{catalog}/collections/{name}")
async def get_collection_by_identifier(
    catalog: str, name: str, actor: ActorDep, lake: LakeDep, response: Response
) -> CollectionOut:
    """A collection by its identifier inside the catalog (``namespace.path.name``)."""
    view = await lake.collections.get(actor, identifier=f"{catalog}.{name}")
    return _out(view, response)


@router.get("/catalogs/{catalog}/search")
async def search_collections(
    catalog: str,
    actor: ActorDep,
    lake: LakeDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    label: Annotated[list[str] | None, Query(description="Repeatable key=value.")] = None,
    state: Annotated[list[State] | None, Query()] = None,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[CollectionOut]:
    """Search a catalog by text, labels and state."""
    query = Search(
        q=q or None,
        labels=tuple(_label(item) for item in label or ()),
        states=frozenset(state) if state else frozenset({State.ACTIVE, State.INCOMPLETE}),
    )
    page = await lake.collections.search(actor, catalog, query, cursor, limit)
    return page_of(CollectionOut, [v.as_dict() for v in page.items], page.next_cursor)


@router.get("/collections/{collection_id}")
async def get_collection(
    collection_id: uuid.UUID, actor: ActorDep, lake: LakeDep, response: Response
) -> CollectionOut:
    """One collection."""
    return _out(await lake.collections.get(actor, collection_id), response)


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: uuid.UUID,
    body: CollectionPatch,
    actor: ActorDep,
    lake: LakeDep,
    response: Response,
    if_match: IfMatch = None,
) -> CollectionOut:
    """Merge-patch the metadata and/or set the schema override (``null`` clears it)."""
    sent = body.model_fields_set
    update = Update(
        metadata_patch=body.metadata or {} if "metadata" in sent else UNSET,
        schema_override=body.schema_override if "schema_override" in sent else UNSET,
    )
    view = await lake.collections.update(actor, collection_id, expected_version(if_match), update)
    return _out(view, response)


@router.post("/collections/{collection_id}/activate")
async def activate_collection(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    response: Response,
    if_match: IfMatch = None,
) -> CollectionOut:
    """Turn a valid draft into an active collection."""
    view = await lake.collections.activate(actor, collection_id, expected_version(if_match))
    return _out(view, response)


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    if_match: IfMatch = None,
    dry_run: Annotated[
        bool, Query(description="Check the caller may delete it; change nothing.")
    ] = False,
) -> None:
    """Delete a collection that has no recorded files."""
    await lake.collections.delete(actor, collection_id, expected_version(if_match), dry_run)


@router.get("/collections/{collection_id}/schema")
async def get_collection_schema(
    collection_id: uuid.UUID, actor: ActorDep, lake: LakeDep
) -> dict[str, Any]:
    """The schema the collection's metadata validates against."""
    return await lake.collections.resolved_schema(actor, collection_id)


@router.get("/collections/{collection_id}/metadata.json")
async def get_sidecar(collection_id: uuid.UUID, actor: ActorDep, lake: LakeDep) -> Response:
    """The canonical ``metadata.json`` the CLI writes beside the files."""
    body = await lake.collections.sidecar(actor, collection_id)
    return Response(content=body, media_type="application/json")


@router.get("/collections/{collection_id}/log")
async def collection_log(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[AuditOut]:
    """Audit entries about the collection, newest first."""
    page = await lake.audit.for_collection(actor, collection_id, cursor, limit)
    return page_of(AuditOut, [e.as_dict() for e in page.items], page.next_cursor)


def _out(view: CollectionView, response: Response) -> CollectionOut:
    set_etag(response, view.collection.version)
    return CollectionOut.model_validate(view.as_dict())


def _label(text: str) -> tuple[str, str]:
    key, sep, value = text.partition("=")
    if not sep:
        key, sep, value = text.partition(":")
    if not sep or not key:
        raise Invalid("labels are key=value", {"label": text})
    return key, value
