"""The ``sessions`` table behind ``pkg.auth.SessionStore``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from huron.pkg.auth import SessionRecord

from .rows import affected_row_count, session_record

if TYPE_CHECKING:
    from datetime import datetime


class PostgresSessionStore:
    """The ``sessions`` table behind ``pkg.auth.SessionStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, session_id: UUID) -> SessionRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, secret_sha256, csrf_token, subject, groups, authentication_method,
                   created_at, last_seen_at, idle_expires_at, absolute_expires_at, revoked_at
            FROM sessions WHERE id = $1
            """,
            session_id,
        )
        if row is None:
            return None
        return session_record(row)

    async def add(self, record: SessionRecord) -> None:
        await self._pool.execute(
            """
            INSERT INTO sessions
                (id, secret_sha256, csrf_token, subject, groups, authentication_method,
                 created_at, last_seen_at, idle_expires_at, absolute_expires_at, revoked_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            record.id,
            record.secret_sha256,
            record.csrf_token,
            record.subject,
            list(record.groups),
            record.authentication_method,
            record.created_at,
            record.last_seen_at,
            record.idle_expires_at,
            record.absolute_expires_at,
            record.revoked_at,
        )

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None:
        await self._pool.execute(
            "UPDATE sessions SET last_seen_at = $2, idle_expires_at = $3 WHERE id = $1",
            session_id,
            last_seen_at,
            idle_expires_at,
        )

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        await self._pool.execute(
            "UPDATE sessions SET revoked_at = $2 WHERE id = $1", session_id, revoked_at
        )

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        tag = await self._pool.execute(
            "UPDATE sessions SET revoked_at = $2 WHERE subject = $1 AND revoked_at IS NULL",
            subject,
            revoked_at,
        )
        return affected_row_count(tag)
