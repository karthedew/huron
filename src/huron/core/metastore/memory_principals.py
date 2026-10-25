"""In-memory principal persistence preserving global subject uniqueness."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from huron.core.security.principals import PrincipalRecord, PrincipalSubjectExists

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from huron.core.security.oidc import OidcUser


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

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Refresh an OIDC identity without linking it to a local account.

        Args:
            user: Verified identity-provider claims.

        Returns:
            The created or refreshed principal, including disabled principals.

        Raises:
            PrincipalSubjectExists: If a new OIDC subject conflicts with another identity.
        """
        existing = next(
            (record for record in self.records.values() if record.idp_subject == user.idp_subject),
            None,
        )
        if existing is not None:
            updated = replace(existing, display_name=user.display_name)
            self.records[updated.id] = updated
            return updated
        if any(record.subject == user.idp_subject for record in self.records.values()):
            raise PrincipalSubjectExists(user.idp_subject)
        record = PrincipalRecord(
            id=uuid4(),
            kind="user",
            subject=user.idp_subject,
            display_name=user.display_name,
            idp_subject=user.idp_subject,
            disabled_at=None,
            created_at=datetime.now(UTC),
        )
        self.records[record.id] = record
        return record
