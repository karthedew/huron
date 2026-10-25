"""Principal identities and persistence contracts for identity administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .oidc import OidcUser


class PrincipalSubjectExists(Exception):
    """A subject is already reserved by a principal of any kind or state."""

    def __init__(self, subject: str):
        """Record the conflicting subject.

        Args:
            subject: The globally reserved subject.
        """
        self.subject = subject
        super().__init__(f"a principal already exists for subject: {subject}")


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
    """Principal lookup and provisioning without automatic cross-credential identity linking."""

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

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Create an OIDC identity or refresh only its display name, including when disabled.

        Args:
            user: Verified identity-provider claims.

        Returns:
            The created or refreshed record; subject collisions raise PrincipalSubjectExists.
        """
        ...
