"""The ``principals`` table behind ``pkg.auth.PrincipalStore``.

The Postgres implementation of the port ``huron.pkg.auth.principals``
declares; ``MemoryPrincipalStore`` lives there beside it. The table is
shared with the RBAC store, which inserts the service-account principals;
this store only ever creates users, and its lookups say which kinds they
see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from huron.pkg.auth import PrincipalRecord, PrincipalSubjectExists
from huron.pkg.catalog.ids import uuid7

from .rows import principal_record

if TYPE_CHECKING:
    from datetime import datetime

    from huron.pkg.auth import OidcUser


class PostgresPrincipalStore:
    """The ``principals`` table behind ``pkg.auth.PrincipalStore``.

    ``upsert_oidc_user`` is the upsert performed on OIDC login: the first
    login for a given ``idp_subject`` inserts the row (``subject`` mirrors
    ``idp_subject``, matching what the bearer-JWT path already treats as
    the OIDC subject), every later one only refreshes the display name.

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

    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None:
        """Return the enabled user with this subject, for password login.

        The WHERE clause folds "unknown username", "disabled account" and
        "this subject names a service account" into the same None, so
        ``verify_password`` runs its constant-shape check against every one
        of those the same way it does an unknown user.

        Args:
            subject: The username the login form submitted.

        Returns:
            The user principal, or None when no enabled user has this
            subject.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, kind, subject, display_name, idp_subject, disabled_at, created_at
            FROM principals
            WHERE subject = $1 AND kind = 'user' AND disabled_at IS NULL
            """,
            subject,
        )
        if row is None:
            return None
        return principal_record(row)

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Create the principal on a first OIDC login, refresh its name on every later one.

        One ``INSERT ... ON CONFLICT (idp_subject) DO UPDATE ... RETURNING``:
        a new ``idp_subject`` inserts a user whose ``subject`` is that same
        value, stamped with the database clock; a known one only replaces
        ``display_name``, leaving ``subject``, ``created_at`` and
        ``disabled_at`` as they were. Unlike ``DO NOTHING``, this form
        always yields exactly one row, so the result is never None. A
        disabled user is returned with ``disabled_at`` set, not refused -
        the login route decides what that means. The conflict target is
        ``idp_subject`` alone: a ``subject`` already held by a password
        user is not an ``idp_subject`` conflict and is not translated here.

        Args:
            user: The identity the provider's callback established.

        Returns:
            The principal row as it is after the upsert.
        """
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

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        """Provision a password user.

        ``subject`` is globally UNIQUE across every principal
        (``0002_rbac``), so a name already claimed - by an OIDC login or
        another password user - surfaces here as
        :class:`~huron.pkg.auth.PrincipalSubjectExists`, the same refusal
        the memory store raises rather than one silently duplicating what
        the other's constraint rejects. The row is a user with no
        ``idp_subject``, enabled, stamped with the database clock; the
        password itself is a separate ``local_credentials`` row the caller
        writes next.

        Args:
            subject: The username the user will log in with.
            display_name: The name shown for the user.

        Returns:
            The principal row as inserted.

        Raises:
            PrincipalSubjectExists: If any principal already holds
                ``subject``.
        """
        try:
            row = await self._pool.fetchrow(
                """
                INSERT INTO principals (id, kind, subject, display_name, created_at)
                VALUES ($1, 'user', $2, $3, now())
                RETURNING id, kind, subject, display_name, idp_subject, disabled_at, created_at
                """,
                uuid7(),
                subject,
                display_name,
            )
        except asyncpg.exceptions.UniqueViolationError as exc:
            raise PrincipalSubjectExists(subject) from exc
        return principal_record(row)

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
