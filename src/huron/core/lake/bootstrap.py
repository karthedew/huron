"""Compose the lake's operations over a unit of work, and seed what every install needs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from huron.core.lake.audit.log import AuditLog
from huron.core.lake.catalogs.operations import Catalogs
from huron.core.lake.collections.lifecycle import Collections
from huron.core.lake.files.commits import Commits
from huron.core.lake.keys import SigningKeys
from huron.core.lake.namespaces.operations import Namespaces
from huron.core.lake.organizations.grants import GrantAdministration
from huron.core.lake.organizations.operations import Organizations
from huron.core.lake.schemas.completeness import Completeness
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME, SchemaEntry
from huron.core.lake.schemas.registry import SchemaRegistry, SchemaResolver
from huron.core.security.rbac import PLATFORM, Role
from huron.pkg.identifiers import new_id
from huron.schema.loader import load_document

if TYPE_CHECKING:
    from huron.core.lake.transaction import UnitOfWork
    from huron.pkg.clock import Clock

__all__ = ["BOOTSTRAP_ACTOR", "BootstrapResult", "Lake", "LakeSettings", "bootstrap", "build_lake"]

BOOTSTRAP_ACTOR = "huron-bootstrap"


@dataclass(frozen=True, slots=True)
class LakeSettings:
    """What the lake needs from configuration."""

    platform_admin_group: str
    key_overlap: timedelta = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Lake:
    """Every lake operation, sharing one unit of work, clock and schema resolver."""

    organizations: Organizations
    grants: GrantAdministration
    schemas: SchemaRegistry
    catalogs: Catalogs
    namespaces: Namespaces
    collections: Collections
    commits: Commits
    audit: AuditLog
    keys: SigningKeys


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """What a bootstrap run created."""

    base_schema: bool
    platform_grant: bool
    signing_key: bool


def build_lake(uow: UnitOfWork, clock: Clock, settings: LakeSettings) -> Lake:
    """Assemble the operations."""
    resolver = SchemaResolver()
    completeness = Completeness(resolver, clock)
    return Lake(
        organizations=Organizations(uow, clock),
        grants=GrantAdministration(uow, clock, settings.platform_admin_group),
        schemas=SchemaRegistry(uow, clock, resolver),
        catalogs=Catalogs(uow, clock, resolver, completeness),
        namespaces=Namespaces(uow, clock),
        collections=Collections(uow, clock, resolver),
        commits=Commits(uow, clock),
        audit=AuditLog(uow),
        keys=SigningKeys(uow, clock, settings.key_overlap),
    )


async def bootstrap(uow: UnitOfWork, clock: Clock, settings: LakeSettings) -> BootstrapResult:
    """Ensure the base schema, the platform admin grant and a current signing key exist.

    Idempotent: a second run creates nothing.
    """
    async with uow.transaction() as tx:
        base_created = False
        if await tx.schemas.latest(None, BASE_SCHEMA_NAME) is None:
            await tx.schemas.insert(
                SchemaEntry(
                    id=new_id(),
                    organization_id=None,
                    name=BASE_SCHEMA_NAME,
                    version=1,
                    extends_id=None,
                    document=load_document("huron-base-v1"),
                    created_at=clock.now(),
                    created_by=BOOTSTRAP_ACTOR,
                )
            )
            base_created = True
        granted = await tx.grants.groups_for_scope(PLATFORM)
        grant_created = False
        if settings.platform_admin_group not in granted.get(Role.PLATFORM_ADMIN, []):
            current = list(granted.get(Role.PLATFORM_ADMIN, []))
            await tx.grants.replace(
                PLATFORM,
                Role.PLATFORM_ADMIN,
                [*current, settings.platform_admin_group],
                BOOTSTRAP_ACTOR,
            )
            grant_created = True
        key = await SigningKeys(uow, clock, settings.key_overlap).ensure_current(tx)
        return BootstrapResult(base_created, grant_created, key is not None)
