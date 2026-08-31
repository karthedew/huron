"""Small immutable values shared by the framework-free catalog modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class EntityRef:
    id: UUID
    slug: str


@dataclass(frozen=True, slots=True)
class RevisionRef:
    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str
    revision_path: str
    committed_by: str
    committed_at: datetime
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    kind: str
    subject_id: UUID
    payload: dict[str, object]
