"""Signing-key reads over committed lake registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.broker import PublicSigningKey, SigningKeyRecord

if TYPE_CHECKING:
    from datetime import datetime

    from huron.core.metastore.lake.memory import LakeTables


class InMemorySigningKeys:
    """Read registered public material in activation order."""

    tables: LakeTables

    async def unexpired(self, retired_after: datetime) -> tuple[SigningKeyRecord, ...]:
        """Return open intervals and keys retired strictly after the supplied bound.

        Args:
            retired_after: Exclusive lower bound for the retirement instant.

        Returns:
            Matching registrations in ascending activation order.
        """
        rows = sorted(self.tables.signing_keys.values(), key=lambda row: row.active_from)
        return tuple(
            SigningKeyRecord(
                PublicSigningKey(row.kid, row.alg, row.public_jwk),
                row.private_ref,
                row.active_from,
                row.retired_at,
            )
            for row in rows
            if row.retired_at is None or row.retired_at > retired_after
        )
