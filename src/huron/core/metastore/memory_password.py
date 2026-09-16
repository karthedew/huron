"""In-memory password credential persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from huron.core.security.password import CredentialRecord


class MemoryCredentialStore:
    """An in-memory credential store keyed by principal identity."""

    def __init__(self, records: Mapping[UUID, CredentialRecord] | None = None):
        """Seed the store with an independent mapping.

        Args:
            records: Initial credentials, copied into the store's own dictionary.
        """
        self.records = dict(records or {})

    async def get(self, principal_id: UUID) -> CredentialRecord | None:
        """Read a principal's credential.

        Args:
            principal_id: The principal to look up.

        Returns:
            Its stored credential or None.
        """
        return self.records.get(principal_id)

    async def upsert(self, record: CredentialRecord) -> None:
        """Replace a principal's credential.

        Args:
            record: The credential keyed by its principal identity.
        """
        self.records[record.principal_id] = record
