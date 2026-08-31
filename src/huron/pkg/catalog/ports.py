"""Consumer-owned protocols; implementing packages conform structurally."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import PurePosixPath
    from uuid import UUID

    from .ingest import IngestLease
    from .models import OutboxEvent, RevisionRecord, RevisionRef


class Clock(Protocol):
    def now(self) -> datetime: ...


class RawStore(Protocol):
    def create_staging(self, ingest_id: UUID) -> PurePosixPath: ...

    def hardlink_from_parent(
        self, parent_payload: PurePosixPath, staging_payload: PurePosixPath, rel_path: str
    ) -> None: ...

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None: ...

    def seal(self, revision_dir: PurePosixPath) -> None: ...

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None: ...


class Metastore(Protocol):
    async def begin_ingest(self, dataset_id: UUID, manifest_sha256: str) -> IngestLease: ...

    async def record_revision(
        self, revision: RevisionRecord, outbox: list[OutboxEvent]
    ) -> None: ...

    async def resolve_tag(self, dataset_id: UUID, tag: str) -> RevisionRef: ...


class SearchProjection(Protocol):
    async def upsert(self, table: str, rows: list[dict[str, object]]) -> None: ...

    async def query(
        self, query: str, visible_project_ids: list[UUID]
    ) -> list[dict[str, object]]: ...


class ScopedCredentials(Protocol):
    expires_at: datetime


class CredentialVendor(Protocol):
    async def vend_read_only(self, repo_prefix: str, ttl_seconds: int) -> ScopedCredentials: ...


class JobDispatcher(Protocol):
    async def submit(
        self, kind: str, subject_id: UUID, image_digest: str, env: dict[str, str]
    ) -> UUID: ...


class Principal(Protocol):
    subject: str


class PrincipalResolver(Protocol):
    async def resolve(self, credential: str) -> Principal: ...
