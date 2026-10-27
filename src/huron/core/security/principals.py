"""Principal identities and persistence contracts for identity administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    """A provisioned identity with immutable kind and globally unique subject."""

    id: UUID
    kind: str
    subject: str
    display_name: str
    idp_subject: str | None
    disabled_at: datetime | None
    created_at: datetime


class PrincipalStore(Protocol):
    """Principal lookup and disablement without cross-credential identity linking."""

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        """Read a principal of any kind and state.

        Args:
            principal_id: Principal identity.

        Returns:
            The record or None.
        """
        ...

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Set the disablement timestamp without changing credential records.

        Args:
            principal_id: Principal identity.
            disabled_at: New timestamp, replacing any earlier one.

        Returns:
            The updated principal or None.
        """
        ...
