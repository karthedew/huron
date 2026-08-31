"""Request bodies owned by ``endpoints/projects.py``."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
