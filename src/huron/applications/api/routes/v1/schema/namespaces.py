"""Namespace bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["NamespaceConfigureIn", "NamespaceIn", "NamespaceOut"]


class NamespaceIn(BaseModel):
    """A new namespace under ``parent`` (empty for the catalog root)."""

    parent: str = ""
    name: str = Field(min_length=1, max_length=63)
    collections_allowed: bool = False


class NamespaceConfigureIn(BaseModel):
    """Whether the namespace may hold collections."""

    collections_allowed: bool


class NamespaceOut(BaseModel):
    """A namespace."""

    id: str
    identifier: str
    catalog: str
    organization: str
    name: str
    path: str
    parent: str
    collections_allowed: bool
    version: int
    created_at: datetime
    created_by: str
    namespace_count: int
    collection_count: int
    disk_path: str
