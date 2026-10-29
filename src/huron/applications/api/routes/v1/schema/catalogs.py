"""Catalog bodies."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from huron.applications.api.routes.v1.schema.schemas import SchemaRefOut

__all__ = ["AssignIn", "AssignOut", "CatalogIn", "CatalogOut", "RecomputeOut"]


class CatalogIn(BaseModel):
    """A new catalog."""

    name: str = Field(min_length=1, max_length=63)
    display_name: str = ""
    description: str = ""
    schema_id: uuid.UUID | None = None


class CatalogOut(BaseModel):
    """A catalog."""

    id: str
    name: str
    organization: str
    display_name: str
    description: str
    schema_: SchemaRefOut = Field(alias="schema", serialization_alias="schema")
    version: int
    created_at: datetime
    created_by: str
    namespace_count: int

    model_config = {"populate_by_name": True}


class AssignIn(BaseModel):
    """The registry entry to assign to a catalog."""

    schema_id: uuid.UUID


class RecomputeOut(BaseModel):
    """How a schema assignment moved the catalog's collections."""

    active: int
    incomplete: int
    changed: int


class AssignOut(BaseModel):
    """The catalog after an assignment and the recompute counts."""

    assigned: CatalogOut
    recompute: RecomputeOut
