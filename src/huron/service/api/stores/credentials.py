"""The ``local_credentials`` table behind ``pkg.auth.CredentialStore``.

The Postgres implementation of the port ``huron.pkg.auth.password``
declares; ``MemoryCredentialStore`` lives there beside it. The table holds
at most one argon2id hash per principal, and the
``local_credentials_kind_guard`` trigger keeps that principal a user, so a
password can never be attached to a service account by any writer.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from huron.pkg.auth import CredentialRecord
from huron.pkg.catalog.errors import ResourceNotFound

from .rows import credential_record


class PostgresCredentialStore:
    """The ``local_credentials`` table behind ``pkg.auth.CredentialStore``.

    One row per principal, keyed by ``principal_id``, holding the hash the
    ``password`` module produced - the store never sees a bare password.
    Shares one ``asyncpg`` pool with the other Postgres stores.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
        self._pool = pool

    async def get(self, principal_id: UUID) -> CredentialRecord | None:
        """Return the principal's password credential, if one is set.

        Args:
            principal_id: The user principal to look up.

        Returns:
            The stored hash and its provenance, or None when the principal
            has no password - which ``verify_password`` treats exactly like
            a wrong one.
        """
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
        """Set or replace the principal's password in one statement.

        ``INSERT ... ON CONFLICT (principal_id) DO UPDATE`` makes first
        password and reset the same operation: the hash, ``updated_at`` and
        ``updated_by`` are replaced together, and nothing else about the
        row survives a replacement.

        ``local_credentials_kind_guard`` fires BEFORE INSERT OR UPDATE and
        looks the principal up itself, so an unknown ``principal_id`` is
        reported by that trigger's RAISE, not a foreign-key violation - the
        FK constraint never gets a chance to run. The trigger raises the
        same way for a principal that exists but is a service account, and
        this store reports that case identically; the user routes check the
        principal's kind before calling, so through the API it is refused
        earlier as a kind mismatch.

        Args:
            record: The credential to store, its hash already computed by
                ``make_credential``.

        Raises:
            ResourceNotFound: If the guard trigger refused the row because
                ``record.principal_id`` names no user principal.
        """
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
