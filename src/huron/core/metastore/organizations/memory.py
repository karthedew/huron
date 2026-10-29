"""In-memory organizations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.organizations.models import Organization
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryOrganizations"]


class MemoryOrganizations:
    """Organizations in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, organization: Organization) -> None:
        """Store a new organization."""
        if any(o.name == organization.name for o in self._state.organizations.values()):
            raise NameTaken(
                f"organization {organization.name!r} exists", {"name": organization.name}
            )
        self._state.organizations[organization.id] = organization

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        """The organization with ``organization_id``."""
        return self._state.organizations.get(organization_id)

    async def get_by_name(self, name: str) -> Organization | None:
        """The organization named ``name``."""
        return next((o for o in self._state.organizations.values() if o.name == name), None)

    async def list(
        self, ids: Collection[uuid.UUID] | None, after: str | None, limit: int
    ) -> Sequence[Organization]:
        """Organizations sorted by name."""
        rows = sorted(self._state.organizations.values(), key=lambda o: o.name)
        rows = [
            o for o in rows if (ids is None or o.id in ids) and (after is None or o.name > after)
        ]
        return rows[:limit]

    async def delete(self, organization_id: uuid.UUID) -> None:
        """Remove an organization."""
        self._state.organizations.pop(organization_id, None)

    async def catalog_count(self, organization_id: uuid.UUID) -> int:
        """How many catalogs the organization has."""
        return sum(1 for c in self._state.catalogs.values() if c.organization_id == organization_id)
