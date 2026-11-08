"""In-memory uploads and removals."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.uploads.models import UploadState

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence
    from datetime import datetime

    from huron.core.lake.uploads.models import Removal, Upload
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryUploads"]


class MemoryUploads:
    """Uploads and removals in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, upload: Upload) -> None:
        """Store a new upload."""
        self._state.uploads[upload.id] = upload

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload with ``upload_id``."""
        return self._state.uploads.get(upload_id)

    async def lock(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload; transactions are already serialized."""
        return self._state.uploads.get(upload_id)

    async def update(self, upload: Upload) -> None:
        """Replace the state, receipt, failure and commit of a stored upload."""
        stored = self._state.uploads.get(upload.id)
        if stored is not None:
            self._state.uploads[upload.id] = replace(
                stored,
                state=upload.state,
                sha256=upload.sha256,
                failure=upload.failure,
                placed_at=upload.placed_at,
                commit_id=upload.commit_id,
                inode=upload.inode,
            )

    async def latest_placements(
        self, collection_id: uuid.UUID, keys: Collection[str]
    ) -> Sequence[Upload]:
        """The latest placed or committed upload of each of ``keys``."""
        wanted = set(keys)
        placements = sorted(
            (
                upload
                for upload in self._state.uploads.values()
                if upload.collection_id == collection_id
                and upload.rel_path_key in wanted
                and upload.state in _PLACEMENTS
            ),
            key=_placement_order,
        )
        latest = {upload.rel_path_key: upload for upload in placements}
        return [latest[key] for key in sorted(latest)]

    async def placed(self, collection_id: uuid.UUID) -> Sequence[Upload]:
        """The placed uploads of a collection, in the order they began."""
        return sorted(
            (
                upload
                for upload in self._state.uploads.values()
                if upload.collection_id == collection_id and upload.state is UploadState.PLACED
            ),
            key=lambda upload: upload.id,
        )

    async def mark_committed(self, upload_ids: Collection[uuid.UUID], commit_id: uuid.UUID) -> None:
        """Move the uploads to ``committed``."""
        for upload_id in upload_ids:
            upload = self._state.uploads.get(upload_id)
            if upload is not None:
                self._state.uploads[upload_id] = replace(
                    upload, state=UploadState.COMMITTED, commit_id=commit_id
                )

    async def insert_removals(self, removals: Sequence[Removal]) -> None:
        """Store new removals as they are."""
        for removal in removals:
            self._state.removals[removal.id] = removal

    async def delete_removals(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Forget the removals of ``keys``."""
        wanted = set(keys)
        self._state.removals = {
            removal_id: removal
            for removal_id, removal in self._state.removals.items()
            if removal.collection_id != collection_id or removal.rel_path_key not in wanted
        }

    async def claim_removals(
        self, now: datetime, stale_before: datetime, limit: int
    ) -> list[Removal]:
        """Claim the oldest claimable removals."""
        claimable = sorted(
            (
                removal
                for removal in self._state.removals.values()
                if removal.claimed_at is None or removal.claimed_at < stale_before
            ),
            key=lambda removal: (removal.created_at, removal.id),
        )
        claimed = [replace(removal, claimed_at=now) for removal in claimable[:limit]]
        for removal in claimed:
            self._state.removals[removal.id] = removal
        return claimed

    async def get_removal(self, removal_id: uuid.UUID) -> Removal | None:
        """The removal with ``removal_id``."""
        return self._state.removals.get(removal_id)

    async def delete_removal(self, removal_id: uuid.UUID) -> None:
        """Forget a removal."""
        self._state.removals.pop(removal_id, None)


_PLACEMENTS = frozenset({UploadState.PLACED, UploadState.COMMITTED})


def _placement_order(upload: Upload) -> tuple[datetime, uuid.UUID]:
    assert upload.placed_at is not None
    return upload.placed_at, upload.id
