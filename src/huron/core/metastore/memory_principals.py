"""In-memory principal persistence preserving global subject uniqueness."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.principals import PrincipalRecord


class MemoryPrincipalStore:
    """Principal records keyed by identity with globally reserved subjects."""

    def __init__(self, records: Mapping[UUID, PrincipalRecord] | None = None):
        """Copy initial records into this store.

        Args:
            records: Initial records keyed by principal identity.
        """
        self.records = dict(records or {})

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        """Read a principal of any kind and state.

        Args:
            principal_id: Principal identity.

        Returns:
            The record or None.
        """
        return self.records.get(principal_id)

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Replace a principal's disablement timestamp.

        Args:
            principal_id: Principal identity.
            disabled_at: New disablement instant.

        Returns:
            The updated principal or None.
        """
        record = self.records.get(principal_id)
        if record is None:
            return None
        updated = replace(record, disabled_at=disabled_at)
        self.records[principal_id] = updated
        return updated
