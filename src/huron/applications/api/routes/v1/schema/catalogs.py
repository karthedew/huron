"""Catalog bodies."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from huron.applications.api.routes.v1.schema.schemas import SchemaRefOut

__all__ = [
    "AssignIn",
    "AssignOut",
    "CatalogIn",
    "CatalogOut",
    "CatalogWriteOut",
    "RecomputeOut",
    "ShareGroupIn",
    "ShareWarningOut",
]

_SHARE_GROUP = "The POSIX group whose members read the catalog's directory."


class CatalogIn(BaseModel):
    """A new catalog."""

    name: str = Field(min_length=1, max_length=63)
    display_name: str = ""
    description: str = ""
    schema_id: uuid.UUID | None = None
    share_group: str | None = Field(default=None, description=_SHARE_GROUP)


class ShareGroupIn(BaseModel):
    """A catalog's new share group; ``null`` clears it."""

    share_group: str | None = Field(description=_SHARE_GROUP)


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
    share_root: str | None = Field(
        description="The configured root of the organization's directory; clients join it with"
        " the relative path, or use their own mount prefix when it is null."
    )
    share_group: str | None = Field(description=_SHARE_GROUP)

    model_config = {"populate_by_name": True}


class ShareWarningOut(BaseModel):
    """A change on disk that the storage administrator must still make."""

    code: str = Field(description="SHARE_GROUP_PENDING: the directory does not have the group.")
    group: str = Field(
        description="The share group, or the gid of the service group when the share group is"
        " cleared."
    )
    detail: str


class CatalogWriteOut(CatalogOut):
    """A catalog after a create or a change, with the warnings of its disk work."""

    warnings: list[ShareWarningOut]


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
