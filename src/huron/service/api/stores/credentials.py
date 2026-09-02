"""The ``local_credentials`` table behind ``pkg.auth.CredentialStore``."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from huron.pkg.auth import CredentialRecord
from huron.pkg.catalog.errors import ResourceNotFound

from .rows import credential_record


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
        return credential_record(row)

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
