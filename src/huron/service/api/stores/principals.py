"""The ``principals`` table behind ``pkg.auth.PrincipalStore``."""

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
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None:
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
        row = await self._pool.fetchrow(
            """
            SELECT id, kind, subject, display_name, idp_subject, disabled_at, created_at
            FROM principals WHERE id = $1
            """,
            principal_id,
        )
        return principal_record(row) if row is not None else None

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        """Provision a password user. ``subject`` is globally UNIQUE across
        every principal (0002), so a name already claimed - by an OIDC login
        or another password user - surfaces here as
        :class:`~huron.pkg.auth.PrincipalSubjectExists`, the same refusal the
        memory store raises rather than one silently duplicating what the
        other's constraint rejects."""
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
        row = await self._pool.fetchrow(
            """
            UPDATE principals SET disabled_at = $2 WHERE id = $1
            RETURNING id, kind, subject, display_name, idp_subject, disabled_at, created_at
            """,
            principal_id,
            disabled_at,
        )
        return principal_record(row) if row is not None else None
