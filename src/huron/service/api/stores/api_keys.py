"""The ``api_keys`` table behind ``pkg.auth.ApiKeyStore``."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from huron.pkg.auth import ApiKeyRecord
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.ids import uuid7

from .rows import affected_row_count, api_key_record


class PostgresApiKeyStore:
    """The ``api_keys`` table behind ``pkg.auth.ApiKeyStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT key_id, owner_subject, name, secret_sha256, scopes, project_id,
                   expires_at, revoked_at, owner_kind
            FROM api_keys WHERE key_id = $1
            """,
            key_id,
        )
        if row is None:
            return None
        return api_key_record(row)

    async def add(self, record: ApiKeyRecord) -> None:
        project_id = UUID(record.project_id) if record.project_id is not None else None
        try:
            await self._pool.execute(
                """
                INSERT INTO api_keys
                    (id, key_id, owner_subject, name, secret_sha256, scopes,
                     project_id, expires_at, revoked_at, owner_kind, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                uuid7(),
                record.key_id,
                record.subject,
                record.name,
                record.secret_sha256,
                list(record.scopes),
                project_id,
                record.expires_at,
                record.revoked_at,
                record.owner_kind,
                datetime.now(UTC),
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise ResourceNotFound(f"project does not exist: {project_id}") from exc

    async def touch_last_used(self, key_id: str) -> None:
        await self._pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE key_id = $1", key_id
        )

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        tag = await self._pool.execute(
            """
            UPDATE api_keys
            SET revoked_at = $2
            WHERE owner_subject = $1
              AND owner_kind = 'service_account'
              AND revoked_at IS NULL
            """,
            subject,
            revoked_at,
        )
        return affected_row_count(tag)
