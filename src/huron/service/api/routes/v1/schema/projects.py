"""Request and response bodies owned by ``endpoints/projects.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateProject(BaseModel):
    slug: str
    title: str = Field(min_length=1)
    description: str = ""
    data_classification: str


class PatchProject(BaseModel):
    #: Accepted only so an attempted change is refused explicitly; slugs are
    #: immutable at every level, for everyone.
    slug: str | None = None
    title: str | None = None
    description: str | None = None


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    slug: str
    title: str
    description: str
    data_classification: str
    version: int
    created_at: datetime
