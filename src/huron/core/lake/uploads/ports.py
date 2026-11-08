"""Persistence port for uploads and the removal outbox."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence
    from datetime import datetime

    from huron.core.lake.uploads.models import Removal, Upload

__all__ = ["UploadStore"]


class UploadStore(Protocol):
    """Reads and writes uploads and the removals the API still has to make."""

    async def insert(self, upload: Upload) -> None:
        """Store a new upload."""
        ...

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload with ``upload_id``."""
        ...

    async def lock(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload, locked for update until the transaction ends."""
        ...

    async def update(self, upload: Upload) -> None:
        """Replace the state, receipt (inode included), failure and commit of a stored upload."""
        ...

    async def latest_placements(
        self, collection_id: uuid.UUID, keys: Collection[str]
    ) -> Sequence[Upload]:
        """The latest placement of each of ``keys``, whoever made it.

        A placement is a ``placed`` or ``committed`` upload. The latest has the latest
        ``placed_at``, and of those the greatest id.
        """
        ...

    async def placed(self, collection_id: uuid.UUID) -> Sequence[Upload]:
        """The ``placed`` uploads of a collection, in the order they began."""
        ...

    async def mark_committed(self, upload_ids: Collection[uuid.UUID], commit_id: uuid.UUID) -> None:
        """Move the uploads to ``committed`` with ``commit_id``."""
        ...

    async def insert_removals(self, removals: Sequence[Removal]) -> None:
        """Store new removals as they are, claimed or not."""
        ...

    async def delete_removals(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Forget the removals of ``keys``, claimed or not."""
        ...

    async def claim_removals(
        self, now: datetime, stale_before: datetime, limit: int
    ) -> list[Removal]:
        """Claim up to ``limit`` removals, oldest first, at ``now``.

        A removal is claimable when nobody claimed it, or when its claim is older than
        ``stale_before`` (the claimer stopped before it finished).
        """
        ...

    async def get_removal(self, removal_id: uuid.UUID) -> Removal | None:
        """The removal with ``removal_id``."""
        ...

    async def delete_removal(self, removal_id: uuid.UUID) -> None:
        """Forget a removal; nothing happens when it is gone already."""
        ...
