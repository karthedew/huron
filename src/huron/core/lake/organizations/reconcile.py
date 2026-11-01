"""Bring the stored organizations in line with the declared ones."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.organizations.grants import record_grant_change
from huron.core.lake.organizations.models import Organization
from huron.core.security.rbac import Scope
from huron.pkg.identifiers import new_id

if TYPE_CHECKING:
    from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
    from huron.core.lake.transaction import Transaction
    from huron.pkg.clock import Clock

__all__ = ["Reconciler", "Reconciliation", "UndeclaredOrganization"]

_PAGE = 500


@dataclass(frozen=True, slots=True)
class UndeclaredOrganization:
    """A stored organization the managed configuration no longer declares; it is kept."""

    name: str
    catalog_count: int


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What reconciling the declared organizations changed, and what it left alone."""

    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    regranted: tuple[str, ...] = ()
    undeclared: tuple[UndeclaredOrganization, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether anything was written."""
        return bool(self.created or self.updated or self.regranted)


class Reconciler:
    """Creates missing declared organizations, updates their text and sets their role groups.

    Each of the four organization-scope roles (Org Admin and the catalog roles its catalogs
    inherit) is set to exactly its declared groups. The organization's name is its key: a
    renamed declaration is a new organization, and the old one becomes undeclared. Undeclared
    organizations are reported, never deleted. A run that finds nothing to change writes
    nothing, audit entries included.
    """

    def __init__(self, clock: Clock, actor: str) -> None:
        self._clock = clock
        self._actor = actor

    async def run(self, tx: Transaction, declarations: Declarations) -> Reconciliation:
        """Reconcile inside ``tx``; nothing happens in unmanaged mode."""
        if not declarations.managed:
            return Reconciliation()
        writer = AuditWriter(tx.audit, self._clock)
        created: list[str] = []
        updated: list[str] = []
        regranted: list[str] = []
        for declared in declarations:
            organization = await tx.organizations.get_by_name(declared.name)
            if organization is None:
                organization = await self._create(tx, writer, declared)
                created.append(declared.name)
            elif await self._update(tx, writer, organization, declared):
                updated.append(declared.name)
            if await self._grant(tx, writer, organization, declared):
                regranted.append(declared.name)
        undeclared = await self._undeclared(tx, declarations)
        return Reconciliation(tuple(created), tuple(updated), tuple(regranted), undeclared)

    async def _create(
        self, tx: Transaction, writer: AuditWriter, declared: DeclaredOrganization
    ) -> Organization:
        organization = Organization(
            id=new_id(),
            name=declared.name,
            display_name=declared.title,
            description=declared.description,
            version=1,
            created_at=self._clock.now(),
            created_by=self._actor,
        )
        await tx.organizations.insert(organization)
        await writer.record(
            self._actor,
            Action.ORGANIZATION_CREATE,
            ObjectType.ORGANIZATION,
            organization.id,
            organization_id=organization.id,
            detail={"name": declared.name},
        )
        return organization

    async def _update(
        self,
        tx: Transaction,
        writer: AuditWriter,
        organization: Organization,
        declared: DeclaredOrganization,
    ) -> bool:
        wanted = {"display_name": declared.title, "description": declared.description}
        changed = sorted(k for k, v in wanted.items() if getattr(organization, k) != v)
        if not changed:
            return False
        await tx.organizations.update(
            replace(
                organization,
                display_name=declared.title,
                description=declared.description,
                version=organization.version + 1,
            )
        )
        await writer.record(
            self._actor,
            Action.ORGANIZATION_UPDATE,
            ObjectType.ORGANIZATION,
            organization.id,
            organization_id=organization.id,
            detail={"name": declared.name, "fields": changed},
        )
        return True

    async def _grant(
        self,
        tx: Transaction,
        writer: AuditWriter,
        organization: Organization,
        declared: DeclaredOrganization,
    ) -> bool:
        scope = Scope.organization(organization.id)
        granted = await tx.grants.groups_for_scope(scope)
        changed = False
        for role, wanted in declared.groups.items():
            if set(granted.get(role, [])) == set(wanted):
                continue
            added, removed = await tx.grants.replace(scope, role, list(wanted), self._actor)
            await record_grant_change(
                writer, self._actor, role, ObjectType.ORGANIZATION, organization.id, added, removed
            )
            changed = True
        return changed

    async def _undeclared(
        self, tx: Transaction, declarations: Declarations
    ) -> tuple[UndeclaredOrganization, ...]:
        found: list[UndeclaredOrganization] = []
        after: str | None = None
        while True:
            rows = await tx.organizations.list(None, after, _PAGE)
            for organization in rows:
                if declarations.get(organization.name) is None:
                    count = await tx.organizations.catalog_count(organization.id)
                    found.append(UndeclaredOrganization(organization.name, count))
            if len(rows) < _PAGE:
                return tuple(found)
            after = rows[-1].name
