"""File and commit bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = ["CommitOut", "CommitResultOut", "FileOut"]


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


class CommitResultOut(BaseModel):
    """What a successful commit answers."""

    version: int
    file_count: int
    commit_id: str
