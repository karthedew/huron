"""PostgreSQL persistence for legacy principal lookup and disablement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .rows import principal_record

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    import asyncpg

    from huron.core.security.principals import PrincipalRecord


class PostgresPrincipalStore:
    """Look up and disable legacy principals through a shared PostgreSQL pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
        self._pool = pool

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        """Return any principal by id - user or service account, enabled or not.

        This is the admin routes' lookup, which is why it hides nothing:
        they inspect ``kind`` and ``disabled_at`` themselves.

        Args:
            principal_id: The principal to read.

        Returns:
            The stored principal, or None when no row has this id.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, kind, subject, display_name, idp_subject, disabled_at, created_at
            FROM principals WHERE id = $1
            """,
            principal_id,
        )
        return principal_record(row) if row is not None else None

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Set ``disabled_at`` on a principal and return the updated row.

        The UPDATE is not restricted by kind; the user routes establish
        that the id names a user before calling. Disabling twice replaces
        the timestamp.

        Args:
            principal_id: The principal to disable.
            disabled_at: The moment to record as the disablement time.

        Returns:
            The principal as stored after the update, or None when no row
            has this id.
        """
        row = await self._pool.fetchrow(
            """
            UPDATE principals SET disabled_at = $2 WHERE id = $1
            RETURNING id, kind, subject, display_name, idp_subject, disabled_at, created_at
            """,
            principal_id,
            disabled_at,
        )
        return principal_record(row) if row is not None else None
