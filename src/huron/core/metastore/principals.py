"""The ``principals`` table behind ``pkg.auth.PrincipalStore``.

The Postgres implementation of the port ``huron.core.security.principals``
declares; ``MemoryPrincipalStore`` lives there beside it. The table is
shared with the RBAC store, which inserts the service-account principals;
this store only ever creates users, and its lookups say which kinds they
see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

from huron.core.foundation.identifiers import uuid7
from huron.core.security.principals import PrincipalRecord, PrincipalSubjectExists

from .rows import principal_record

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.oidc import OidcUser

#: The name Postgres gives ``principals.subject``'s column-level UNIQUE
#: constraint, absent an explicit ``CONSTRAINT`` clause in the migration.
_SUBJECT_UNIQUE_CONSTRAINT = "principals_subject_key"


class PostgresPrincipalStore:
    """The ``principals`` table behind ``pkg.auth.PrincipalStore``.

    ``upsert_oidc_user`` records a provider identity: the first
    upsert for a given ``idp_subject`` inserts the row (``subject`` mirrors
    ``idp_subject``, matching what the bearer-JWT path already treats as
    the OIDC subject), every later one only refreshes the display name. A
    first-ever ``idp_subject`` that collides with another principal's
    ``subject`` is refused, never auto-linked.

    ``subject`` is UNIQUE across every principal and ``idp_subject`` across
    every user, and both are set once, at creation, and never move. Shares
    one ``asyncpg`` pool with the other Postgres stores.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
        self._pool = pool

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Create a provider identity or refresh its existing display name.

        One ``INSERT ... ON CONFLICT (idp_subject) DO UPDATE ... RETURNING``:
        a new ``idp_subject`` inserts a user whose ``subject`` is that same
        value, stamped with the database clock; a known one only replaces
        ``display_name``, leaving ``subject``, ``created_at`` and
        ``disabled_at`` as they were. Unlike ``DO NOTHING``, this form
        always yields exactly one row, so the result is never None. A
        disabled user is returned with ``disabled_at`` set, not refused -
        the caller decides what that means. The conflict target is
        ``idp_subject`` alone: a first-ever ``idp_subject`` that instead
        collides with the ``subject`` UNIQUE constraint - some other
        principal already holds it - is not an ``idp_subject`` conflict,
        so it falls through to a raw ``UniqueViolationError`` on the
        ``subject`` column that this method translates into a refusal.

        Args:
            user: The identity the provider's callback established.

        Returns:
            The principal row as it is after the upsert.

        Raises:
            PrincipalSubjectExists: If ``idp_subject`` is not yet known and
                some other principal already holds it as ``subject``.
            asyncpg.exceptions.UniqueViolationError: If the insert violates
                a UNIQUE constraint other than ``subject`` - not expected
                against the current schema, where ``idp_subject`` is the
                statement's only other conflict target and is handled by
                ``ON CONFLICT``.
        """
        try:
            row = await self._pool.fetchrow(
                """
                INSERT INTO principals (id, kind, subject, display_name, idp_subject, created_at)
                VALUES ($1, 'user', $2, $3, $2, now())
                ON CONFLICT (idp_subject) DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING id, kind, subject, display_name, idp_subject, disabled_at, created_at
                """,
                uuid7(),
                user.idp_subject,
                user.display_name,
            )
        except asyncpg.exceptions.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _SUBJECT_UNIQUE_CONSTRAINT:
                raise
            raise PrincipalSubjectExists(user.idp_subject) from exc
        # INSERT ... ON CONFLICT DO UPDATE ... RETURNING always yields
        # exactly one row - unlike DO NOTHING, there is no way to affect zero.
        return principal_record(row)

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
