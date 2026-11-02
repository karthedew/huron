"""The schema registry's platform scope and entry reads."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.applications.api.routes.v1.schema.schemas import SchemaIn, SchemaOut

__all__ = ["router"]

router = APIRouter(tags=["schemas"])


@router.get("/platform/schemas")
async def list_platform_schemas(
    actor: ActorDep, lake: LakeDep, cursor: Cursor = None, limit: Limit = None
) -> Page[SchemaOut]:
    """Platform-scoped registry entries."""
    page = await lake.schemas.list(actor, None, cursor, limit)
    return page_of(SchemaOut, [e.as_dict() for e in page.items], page.next_cursor)


@router.post("/platform/schemas", status_code=status.HTTP_201_CREATED)
async def publish_platform_schema(body: SchemaIn, actor: ActorDep, lake: LakeDep) -> SchemaOut:
    """Publish the next version of a platform schema."""
    entry = await lake.schemas.publish(actor, None, body.name, body.extends_id, body.document)
    return SchemaOut.model_validate(entry.as_dict())


@router.get("/schemas/{schema_id}")
async def get_schema(schema_id: uuid.UUID, actor: ActorDep, lake: LakeDep) -> SchemaOut:
    """One registry entry."""
    entry = await lake.schemas.get(actor, schema_id)
    return SchemaOut.model_validate(entry.as_dict())


@router.get("/schemas/{schema_id}/resolved")
async def get_resolved_schema(
    schema_id: uuid.UUID, actor: ActorDep, lake: LakeDep
) -> dict[str, Any]:
    """The entry composed with everything it extends."""
    return await lake.schemas.resolved(actor, schema_id)
