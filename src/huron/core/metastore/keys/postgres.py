"""PostgreSQL signing keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.broker.keys import SigningKey

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from huron.core.metastore.rows import Db

__all__ = ["PostgresKeys"]


class PostgresKeys:
    """Signing keys in table ``huron.signing_keys``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def list_keys(self) -> Sequence[SigningKey]:
        """Every key, newest first."""
        rows = await self._db.fetch(
            "select kid, private_pem, public_jwk, created_at, retired_at"
            " from huron.signing_keys order by created_at desc"
        )
        return [SigningKey(**row) for row in rows]

    async def insert_key(self, key: SigningKey) -> None:
        """Store a new key."""
        await self._db.execute(
            "insert into huron.signing_keys (kid, private_pem, public_jwk, created_at, retired_at)"
            " values ($1, $2, $3, $4, $5)",
            key.kid,
            key.private_pem,
            key.public_jwk,
            key.created_at,
            key.retired_at,
        )

    async def retire_key(self, kid: str, at: datetime) -> None:
        """Mark a key retired."""
        await self._db.execute(
            "update huron.signing_keys set retired_at = $2 where kid = $1 and retired_at is null",
            kid,
            at,
        )
