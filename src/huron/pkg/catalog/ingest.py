"""Pure raw-ingest state and upload-plan mechanics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from .errors import IllegalIngestTransition, IngestSessionExpired

if TYPE_CHECKING:
    from uuid import UUID

    from .manifest import Manifest, ManifestEntry


class IngestState(StrEnum):
    PREPARING = "PREPARING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({IngestState.COMMITTED, IngestState.ABORTED, IngestState.FAILED})
_TRANSITIONS = {
    IngestState.PREPARING: frozenset(
        {IngestState.UPLOADING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.UPLOADING: frozenset(
        {IngestState.VERIFYING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.VERIFYING: frozenset(
        {IngestState.COMMITTING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.COMMITTING: frozenset({IngestState.COMMITTED, IngestState.FAILED}),
    IngestState.COMMITTED: frozenset(),
    IngestState.ABORTED: frozenset(),
    IngestState.FAILED: frozenset(),
}


class UploadAction(StrEnum):
    UPLOAD = "upload"
    HARDLINK = "hardlink"


@dataclass(frozen=True, slots=True)
class UploadPlanEntry:
    file: ManifestEntry
    action: UploadAction
    parent_path: str | None = None


@dataclass(frozen=True, slots=True)
class IngestLease:
    ingest_id: UUID
    dataset_id: UUID
    revision_id: UUID
    revision_number: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IngestSession:
    lease: IngestLease
    state: IngestState
    manifest_sha256: str
    etag: int = 1

    def transition(self, target: IngestState, *, now: datetime | None = None) -> IngestSession:
        current_time = now or datetime.now(UTC)
        if current_time >= self.lease.expires_at and self.state not in TERMINAL_STATES:
            raise IngestSessionExpired(f"ingest session {self.lease.ingest_id} has expired")
        if target not in _TRANSITIONS[self.state]:
            raise IllegalIngestTransition(f"cannot transition {self.state} to {target}")
        return replace(self, state=target, etag=self.etag + 1)

    def heartbeat(
        self, *, now: datetime | None = None, ttl: timedelta = timedelta(hours=2)
    ) -> IngestSession:
        current_time = now or datetime.now(UTC)
        if self.state in TERMINAL_STATES or current_time >= self.lease.expires_at:
            raise IngestSessionExpired(f"ingest session {self.lease.ingest_id} is not renewable")
        return replace(
            self,
            lease=replace(self.lease, expires_at=current_time + ttl),
            etag=self.etag + 1,
        )


def compute_upload_plan(
    manifest: Manifest, parent_manifest: Manifest | None = None
) -> tuple[UploadPlanEntry, ...]:
    parent_by_path = (
        {entry.path: entry for entry in parent_manifest.files} if parent_manifest else {}
    )
    plan: list[UploadPlanEntry] = []
    for entry in manifest.files:
        parent = parent_by_path.get(entry.path)
        unchanged = (
            parent is not None and parent.sha256 == entry.sha256 and parent.size == entry.size
        )
        plan.append(
            UploadPlanEntry(
                file=entry,
                action=UploadAction.HARDLINK if unchanged else UploadAction.UPLOAD,
                parent_path=entry.path if unchanged else None,
            )
        )
    return tuple(plan)
