"""The ``api_keys`` table behind ``pkg.auth.ApiKeyStore``.

The Postgres implementation of the ``ApiKeyWriter`` port: ``get`` is the
read ``ApiKeyResolver`` depends on, ``add``, ``touch_last_used`` and
``revoke_all_for`` the writes the routes and the credential resolver need.
Its in-memory counterpart, ``MemoryApiKeyStore``, lives beside the port's
read half in ``huron.pkg.auth``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.ids import uuid7

from .rows import affected_row_count, api_key_record

if TYPE_CHECKING:
    from huron.pkg.auth import ApiKeyRecord


class PostgresApiKeyStore:
    """The ``api_keys`` table behind ``pkg.auth.ApiKeyStore``.

    Satisfies ``ApiKeyWriter`` structurally. The table keeps only the
    secret's SHA-256, never the secret; ``key_id`` is the unique public
    handle every lookup uses, and the row's own ``id`` is an internal
    surrogate nothing outside this store sees. ``project_id`` is a foreign
    key to ``projects``, so the store is only wired once those rows are
    real. Shares one ``asyncpg`` pool with the other Postgres stores.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
        self._pool = pool

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        """Return the key with this public handle, whatever its state.

        Revoked and expired keys are returned as stored; ``ApiKeyResolver``
        is what turns ``revoked_at`` and ``expires_at`` into refusals.

        Args:
            key_id: The public handle from the ``hk_{key_id}_{secret}``
                credential.

        Returns:
            The stored key, or None when no key has this handle.
        """
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
        """Insert a freshly issued key.

        The row gets a new surrogate id and the current time as
        ``created_at``; everything else is the record as ``create_api_key``
        built it, with the record's string ``project_id`` parsed back into
        the uuid the column holds. ``key_id`` is 16 random hex characters,
        so a collision on its UNIQUE constraint is not a request the caller
        could have provoked - it is a 128-bit accident, and this store
        reports it as the bug it is rather than a client error.

        Args:
            record: The key to store, its secret already hashed.

        Raises:
            ResourceNotFound: If ``record.project_id`` names no project (the
                foreign key refused the row).
            RuntimeError: If ``record.key_id`` collides with an
                already-stored key.
        """
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
        except asyncpg.UniqueViolationError as exc:
            raise RuntimeError(f"key_id collision: {record.key_id}") from exc

    async def touch_last_used(self, key_id: str) -> None:
        """Stamp the key's ``last_used_at`` with the database clock.

        Bookkeeping only. An unknown ``key_id`` updates nothing and raises
        nothing; the caller already treats any failure here as non-fatal.

        Args:
            key_id: The public handle of the key that just authenticated.
        """
        await self._pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE key_id = $1", key_id
        )

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke every active key a subject owns, whatever its ``owner_kind``.

        The UPDATE is restricted to rows whose ``revoked_at`` is still NULL,
        so an earlier revocation keeps its own timestamp.

        Args:
            subject: The owner whose keys are revoked.
            revoked_at: The moment to record on each key.

        Returns:
            How many keys this call revoked, read off the command tag.
        """
        tag = await self._pool.execute(
            """
            UPDATE api_keys
            SET revoked_at = $2
            WHERE owner_subject = $1
              AND revoked_at IS NULL
            """,
            subject,
            revoked_at,
        )
        return affected_row_count(tag)
