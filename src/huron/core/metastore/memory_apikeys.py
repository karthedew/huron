"""In-memory API-key persistence and usage bookkeeping."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from huron.core.security.apikeys import ApiKeyRecord


class MemoryApiKeyStore:
    """API keys keyed by their public handle, including expired and revoked records."""

    def __init__(self, records: Mapping[str, ApiKeyRecord] | None = None):
        """Copy initial records into this process's store.

        Args:
            records: Initial records keyed by key handle.
        """
        self.records = dict(records or {})
        self.touched: list[str] = []

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        """Read a record regardless of expiry or revocation.

        Args:
            key_id: The public key handle.

        Returns:
            The record or None.
        """
        return self.records.get(key_id)

    async def add(self, record: ApiKeyRecord) -> None:
        """Store a record, replacing the same handle.

        Args:
            record: The issued record, with no plaintext secret.
        """
        self.records[record.key_id] = record

    async def touch_last_used(self, key_id: str) -> None:
        """Record a usage observation, including unknown handles.

        Args:
            key_id: The key that authenticated a request.
        """
        self.touched.append(key_id)

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke each live key while retaining previous revocation timestamps.

        Args:
            subject: Owner subject across principal kinds.
            revoked_at: Instant for newly revoked keys.

        Returns:
            The number newly revoked.
        """
        count = 0
        for key_id, record in self.records.items():
            if record.subject == subject and record.revoked_at is None:
                self.records[key_id] = replace(record, revoked_at=revoked_at)
                count += 1
        return count
