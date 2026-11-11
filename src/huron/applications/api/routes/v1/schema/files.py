"""File, commit and commit request bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from huron.core.lake.publications.models import MAX_BASE_VERSION, Resolution

__all__ = [
    "AddIn",
    "CommitIn",
    "CommitOut",
    "CommitPreviewOut",
    "CommitRequestOut",
    "FileOut",
    "RefusalOut",
    "ResolutionIn",
]


class FileOut(BaseModel):
    """A recorded file."""

    rel_path: str
    size: int
    sha256: str
    recorded_at: datetime
    recorded_by: str
    commit_id: str


class CommitOut(BaseModel):
    """An applied commit."""

    id: str
    base_version: int
    new_version: int
    adds: int
    removes: int
    host: str
    message: str | None
    actor: str
    created_at: datetime


class AddIn(BaseModel):
    """A file that a commit adds or replaces: the sealed bytes of one upload."""

    model_config = ConfigDict(extra="forbid")

    rel_path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
        description="The sha256 of the file. A commit needs it; a dry run can leave it out.",
    )
    upload_id: uuid.UUID | None = Field(
        default=None,
        description="The current upload ID of a ready upload attempt. A commit needs it; a dry"
        " run can leave it out.",
    )


class CommitIn(BaseModel):
    """The body of a commit to one collection: at most 10,000 adds and removes together."""

    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID | None = Field(
        default=None,
        description="The client's ID of the request. A commit needs it; a dry run can leave it"
        " out. The same ID with the same body gets the saved outcome again.",
    )
    base_version: int = Field(ge=0, le=MAX_BASE_VERSION)
    adds: list[AddIn]
    removes: list[str]
    host: str = Field(min_length=1, max_length=255)
    message: str | None = Field(default=None, max_length=2000)


class RefusalOut(BaseModel):
    """The problem that refused or blocked a commit request."""

    code: str
    detail: str
    context: dict[str, Any]


class CommitRequestOut(BaseModel):
    """The saved state of a commit request.

    A ``succeeded`` request has its ``version``, ``file_count`` and ``commit_id``. A ``rejected``
    or ``blocked`` request has its ``refusal``.
    """

    request_id: str
    state: str = Field(description="rejected, accepted, blocked, succeeded or abandoned.")
    collection_id: str | None = Field(description="null when the collection is deleted.")
    version: int | None
    file_count: int | None
    commit_id: str | None
    refusal: RefusalOut | None


class CommitPreviewOut(BaseModel):
    """What a commit would make: the answer of a dry run."""

    version: int
    file_count: int


class ResolutionIn(BaseModel):
    """What a platform administrator does with the blocked commit request of a collection."""

    model_config = ConfigDict(extra="forbid")

    resolution: Resolution = Field(
        description="retry: run the entries that are not done again. abandon: end a request of"
        " which no entry is done, free the collection and make its uploads ready again."
    )
