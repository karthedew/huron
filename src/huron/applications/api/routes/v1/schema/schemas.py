"""Schema registry bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["SchemaIn", "SchemaOut", "SchemaRefOut"]


class SchemaIn(BaseModel):
    """A new version of a named schema."""

    name: str = Field(min_length=1, max_length=63)
    extends_id: uuid.UUID | None = None
    document: dict[str, Any]


class SchemaRefOut(BaseModel):
    """A short reference to a registry entry."""

    id: str
    name: str
    version: int


class SchemaOut(BaseModel):
    """A registry entry."""

    id: str
    organization_id: str | None
    scope: str
    name: str
    version: int
    extends_id: str | None
    document: dict[str, Any]
    created_at: datetime
    created_by: str
