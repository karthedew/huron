"""Postgres-backed local credentials, sessions, and the principal-upsert seam.

Same conventions as ``postgres_rbac.py``: every method maps directly onto
one of the tables ``migrations/versions/0005_auth.py`` creates, and a
guard trigger (``local_credentials_kind_guard``) backstops what the API
layer is expected to have validated already, for rows written outside it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from huron.pkg.auth import CredentialRecord, PrincipalRecord, PrincipalSubjectExists, SessionRecord
from huron.pkg.catalog.ids import uuid7
from huron.service.api.repository import ResourceNotFound

if TYPE_CHECKING:
    from datetime import datetime

    from huron.pkg.auth import OidcUser


def _credential_record_from_row(row: asyncpg.Record) -> CredentialRecord:
    return CredentialRecord(
        principal_id=row["principal_id"],
        password_hash=row["password_hash"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


def _session_record_from_row(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        secret_sha256=row["secret_sha256"],
        csrf_token=row["csrf_token"],
        subject=row["subject"],
        groups=frozenset(row["groups"]),
        authentication_method=row["authentication_method"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        idle_expires_at=row["idle_expires_at"],
        absolute_expires_at=row["absolute_expires_at"],
        revoked_at=row["revoked_at"],
    )


def _principal_record_from_row(row: asyncpg.Record) -> PrincipalRecord:
    return PrincipalRecord(
        id=row["id"],
        kind=row["kind"],
        subject=row["subject"],
        display_name=row["display_name"],
        idp_subject=row["idp_subject"],
        disabled_at=row["disabled_at"],
        created_at=row["created_at"],
    )


def _affected_row_count(tag: str) -> int:
    """asyncpg's execute() returns a command tag like ``"UPDATE 3"``."""
    return int(tag.rsplit(" ", 1)[-1])


class PostgresCredentialStore:
    """The ``local_credentials`` table behind ``pkg.auth.CredentialStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, principal_id: UUID) -> CredentialRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT principal_id, password_hash, updated_at, updated_by
            FROM local_credentials WHERE principal_id = $1
            """,
            principal_id,
        )
        if row is None:
            return None
        return _credential_record_from_row(row)

    async def upsert(self, record: CredentialRecord) -> None:
        try:
            await self._pool.execute(
                """
                INSERT INTO local_credentials (principal_id, password_hash, updated_at, updated_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (principal_id) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                """,
                record.principal_id,
                record.password_hash,
                record.updated_at,
                record.updated_by,
            )
        except asyncpg.exceptions.RaiseError as exc:
            # local_credentials_kind_guard fires BEFORE INSERT OR UPDATE and
            # looks the principal up itself, so an unknown principal_id is
            # reported by that trigger's RAISE, not a foreign-key violation -
            # the FK constraint never gets a chance to run.
            raise ResourceNotFound(f"principal does not exist: {record.principal_id}") from exc


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
        return _session_record_from_row(row)

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
        return _affected_row_count(tag)


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
        return _principal_record_from_row(row)

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
        return _principal_record_from_row(row)

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, kind, subject, display_name, idp_subject, disabled_at, created_at
            FROM principals WHERE id = $1
            """,
            principal_id,
        )
        return _principal_record_from_row(row) if row is not None else None

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
        return _principal_record_from_row(row)

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        row = await self._pool.fetchrow(
            """
            UPDATE principals SET disabled_at = $2 WHERE id = $1
            RETURNING id, kind, subject, display_name, idp_subject, disabled_at, created_at
            """,
            principal_id,
            disabled_at,
        )
        return _principal_record_from_row(row) if row is not None else None
