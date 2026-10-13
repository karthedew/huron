"""Persistence for external publication acknowledgements and bounded revision discovery."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RawRegistration:
    """Durable publication state derived from a commit and its acknowledgement."""

    state: Literal["pending", "registered"]
    dataset_id: UUID
    revision_id: UUID


class RawPublicationStore(Protocol):
    """Committed revisions remain pending until their external registration is acknowledged."""

    async def registered(self, revision_id: UUID) -> bool:
        """Read whether a committed revision's catalog registration was acknowledged.

        Args:
            revision_id: Committed revision identity.

        Returns:
            True after the durable acknowledgement.
        """
        ...

    async def acknowledge(self, revision_id: UUID) -> None:
        """Durably acknowledge registration without altering the revision.

        Args:
            revision_id: Committed revision whose target was checked by the workflow.
        """
        ...

    async def revision_ids(
        self, dataset_id: UUID, *, before: int | None, limit: int
    ) -> tuple[UUID, ...]:
        """Page immutable revisions newest first.

        Args:
            dataset_id: Already authorized dataset identity.
            before: Exclusive revision-number cursor, or None for the first page.
            limit: Maximum returned rows.

        Returns:
            Committed revision identities.
        """
        ...
