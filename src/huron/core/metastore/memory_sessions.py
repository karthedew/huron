"""In-memory browser-session persistence."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.sessions import SessionRecord


class MemorySessionStore:
    """Session records with observable activity and independent immutable successors."""

    def __init__(self, records: Mapping[UUID, SessionRecord] | None = None):
        """Copy initial records into this store.

        Args:
            records: Initial sessions keyed by identity.
        """
        self.records = dict(records or {})
        self.touched: list[UUID] = []

    async def get(self, session_id: UUID) -> SessionRecord | None:
        """Read a session in any state.

        Args:
            session_id: Session identity.

        Returns:
            The record or None.
        """
        return self.records.get(session_id)

    async def add(self, record: SessionRecord) -> None:
        """Store a session, replacing the same identity.

        Args:
            record: Complete issued session.
        """
        self.records[record.id] = record

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None:
        """Record activity and slide the idle deadline of an existing session.

        Args:
            session_id: Session identity, observed even when unknown.
            last_seen_at: Activity instant.
            idle_expires_at: New deadline bounded by the resolver.
        """
        self.touched.append(session_id)
        record = self.records.get(session_id)
        if record is not None:
            self.records[session_id] = replace(
                record, last_seen_at=last_seen_at, idle_expires_at=idle_expires_at
            )

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        """Revoke one session; an unknown identity is a no-op.

        Args:
            session_id: Session identity.
            revoked_at: Revocation instant.
        """
        record = self.records.get(session_id)
        if record is not None:
            self.records[session_id] = replace(record, revoked_at=revoked_at)

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke live sessions while retaining earlier revocation timestamps.

        Args:
            subject: Owner subject.
            revoked_at: Timestamp for newly revoked sessions.

        Returns:
            The number newly revoked.
        """
        count = 0
        for session_id, record in self.records.items():
            if record.subject == subject and record.revoked_at is None:
                self.records[session_id] = replace(record, revoked_at=revoked_at)
                count += 1
        return count
