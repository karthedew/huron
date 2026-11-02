"""Organization bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["OrganizationIn", "OrganizationOut"]


class OrganizationIn(BaseModel):
    """A new organization."""

    name: str = Field(min_length=1, max_length=63)
    display_name: str = ""
    description: str = ""


class OrganizationOut(BaseModel):
    """An organization."""

    id: str
    name: str
    display_name: str
    description: str
    version: int
    created_at: datetime
    created_by: str
    catalog_count: int
    declared: bool = Field(description="Whether the service configuration declares it.")
    root: str | None = Field(description="The configured parent of the organization's directory.")
    path: str | None = Field(description="The organization's directory, root/name.")
    export: str | None = Field(description="The NFS export the configuration names, if any.")
