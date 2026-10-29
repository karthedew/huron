"""Collection bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from huron.applications.api.routes.v1.schema.schemas import SchemaRefOut

__all__ = ["CollectionIn", "CollectionOut", "CollectionPatch", "ProblemOut"]


class CollectionIn(BaseModel):
    """A new draft collection."""

    name: str = Field(min_length=1, max_length=63)
    metadata: dict[str, Any] | None = None


class CollectionPatch(BaseModel):
    """A metadata merge patch and/or a schema override (``null`` clears the override)."""

    metadata: dict[str, Any] | None = None
    schema_override: dict[str, Any] | None = None


class ProblemOut(BaseModel):
    """One validation problem."""

    path: str
    message: str
    rule: str


class CollectionOut(BaseModel):
    """A collection."""

    id: str
    identifier: str
    organization: str
    catalog: str
    namespace: str
    name: str
    state: str
    version: int
    metadata: dict[str, Any]
    schema_override: dict[str, Any] | None
    schema_: SchemaRefOut = Field(alias="schema", serialization_alias="schema")
    file_count: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    activated_at: datetime | None
    path: str | None
    problems: list[ProblemOut]

    model_config = {"populate_by_name": True}
