"""The ``sessions`` table behind ``pkg.auth.SessionStore``.

The Postgres implementation of the port ``huron.pkg.auth.sessions``
declares; ``MemorySessionStore`` lives there beside it. The design the
table serves is described with the port: the browser holds
``hs_{id}_{secret}``, the row keeps only the secret's SHA-256, expiry is
double-bounded, and revocation is a row update the next request sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .rows import affected_row_count, session_record

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    import asyncpg

    from huron.pkg.auth import SessionRecord


class PostgresSessionStore:
    """The ``sessions`` table behind ``pkg.auth.SessionStore``.

    Every method is one statement against the row's primary key or the
    ``sessions_subject_active`` partial index. The store judges nothing:
    expiry and revocation are stored as timestamps and interpreted by
    ``SessionResolver``. The table's CHECK keeps ``idle_expires_at`` at or
    before ``absolute_expires_at``, so a bad idle extension can never
    outlive the session. Shares one ``asyncpg`` pool with the other
    Postgres stores.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
        self._pool = pool

    async def get(self, session_id: UUID) -> SessionRecord | None:
        """Return the session with this id, whatever its state.

        Expired and revoked sessions are returned as stored;
        ``SessionResolver`` is what turns their timestamps into refusals.

        Args:
            session_id: The id from the ``hs_{id}_{secret}`` cookie value.

        Returns:
            The stored session, or None when no row has this id.
        """
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
        """Insert a session exactly as ``create_session`` built it.

        Every column comes from the record, ``groups`` as an array; the
        store generates nothing, so the row is the record and the record
        is the row. No error is translated: ids are random uuids, and a
        record from ``create_session`` satisfies the table's CHECKs.

        Args:
            record: The session to store, its secret already hashed.
        """
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
        """Slide the session's idle window forward.

        ``SessionResolver`` calls this at most once per ``TOUCH_INTERVAL``
        and clamps ``idle_expires_at`` to the absolute expiry, which the
        table's CHECK would otherwise refuse. An unknown id updates nothing
        and raises nothing.

        Args:
            session_id: The session that was just used.
            last_seen_at: The moment of that use.
            idle_expires_at: The new idle deadline, no later than the
                session's ``absolute_expires_at``.
        """
        await self._pool.execute(
            "UPDATE sessions SET last_seen_at = $2, idle_expires_at = $3 WHERE id = $1",
            session_id,
            last_seen_at,
            idle_expires_at,
        )

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        """Revoke one session, effective on its next request.

        Unconditional: revoking again replaces the earlier timestamp. An
        unknown id updates nothing and raises nothing.

        Args:
            session_id: The session to revoke.
            revoked_at: The moment to record.
        """
        await self._pool.execute(
            "UPDATE sessions SET revoked_at = $2 WHERE id = $1", session_id, revoked_at
        )

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke every active session of one subject.

        This is what a password reset or a user disablement calls so no
        browser stays logged in past it. Only rows whose ``revoked_at`` is
        still NULL are touched - the ``sessions_subject_active`` index
        covers exactly those - so an earlier revocation keeps its own
        timestamp and is not counted again.

        Args:
            subject: The subject whose sessions are revoked.
            revoked_at: The moment to record on each session.

        Returns:
            How many sessions this call revoked, read off the command tag.
        """
        tag = await self._pool.execute(
            "UPDATE sessions SET revoked_at = $2 WHERE subject = $1 AND revoked_at IS NULL",
            subject,
            revoked_at,
        )
        return affected_row_count(tag)
