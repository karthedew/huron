"""Compose the lake's operations over a unit of work, and seed what every install needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from huron.core.lake.audit.log import AuditLog
from huron.core.lake.catalogs.operations import Catalogs
from huron.core.lake.collections.lifecycle import Collections
from huron.core.lake.files.commits import Commits
from huron.core.lake.keys import SigningKeys
from huron.core.lake.namespaces.operations import Namespaces
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
from huron.core.lake.organizations.grants import GrantAdministration
from huron.core.lake.organizations.operations import Organizations
from huron.core.lake.organizations.reconcile import Reconciler, Reconciliation
from huron.core.lake.repairs.operations import Repairs
from huron.core.lake.schemas.completeness import Completeness
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME, SchemaEntry
from huron.core.lake.schemas.registry import SchemaRegistry, SchemaResolver
from huron.core.lake.uploads.models import ReceiptMode
from huron.core.lake.uploads.operations import Uploads
from huron.core.security.rbac import PLATFORM, Role
from huron.pkg.identifiers import new_id
from huron.schema.loader import load_document

if TYPE_CHECKING:
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.pkg.clock import Clock

__all__ = ["BOOTSTRAP_ACTOR", "BootstrapResult", "Lake", "LakeSettings", "bootstrap", "build_lake"]

BOOTSTRAP_ACTOR = "huron-bootstrap"


@dataclass(frozen=True, slots=True)
class LakeSettings:
    """What the lake needs from configuration; ``organizations`` are the declared ones.

    ``receipt_mode`` decides whether a commit needs a receipt for each add; ``upload_ttl`` is
    how long a receipt stays good; ``upload_max_size`` is the largest upload in bytes, ``0`` for
    no limit.
    """

    platform_admin_group: str
    key_overlap: timedelta = timedelta(hours=24)
    organizations: Declarations = UNMANAGED
    receipt_mode: ReceiptMode = ReceiptMode.REQUIRED
    upload_ttl: timedelta = timedelta(hours=24)
    upload_max_size: int = 0


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
    uploads: Uploads
    repairs: Repairs
    audit: AuditLog
    keys: SigningKeys


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """What a bootstrap run created, and how it reconciled the declared organizations."""

    base_schema: bool
    platform_grant: bool
    signing_key: bool
    organizations: Reconciliation = field(default_factory=Reconciliation)


def build_lake(uow: UnitOfWork, clock: Clock, settings: LakeSettings) -> Lake:
    """Assemble the operations."""
    resolver = SchemaResolver()
    completeness = Completeness(resolver, clock)
    return Lake(
        organizations=Organizations(uow, clock, settings.organizations),
        grants=GrantAdministration(
            uow, clock, settings.platform_admin_group, settings.organizations
        ),
        schemas=SchemaRegistry(uow, clock, resolver),
        catalogs=Catalogs(uow, clock, resolver, completeness),
        namespaces=Namespaces(uow, clock),
        collections=Collections(uow, clock, resolver),
        commits=Commits(uow, clock, settings.receipt_mode, settings.upload_ttl),
        uploads=Uploads(uow, clock, ttl=settings.upload_ttl, max_size=settings.upload_max_size),
        repairs=Repairs(uow),
        audit=AuditLog(uow),
        keys=SigningKeys(uow, clock, settings.key_overlap),
    )


async def bootstrap(uow: UnitOfWork, clock: Clock, settings: LakeSettings) -> BootstrapResult:
    """Ensure the base schema, the platform admin grant, a current signing key and the declared
    organizations exist, in one transaction under the bootstrap lock.

    Idempotent: a second run writes nothing.
    """
    async with uow.transaction() as tx:
        await tx.lock_bootstrap()
        base_created = await _ensure_base_schema(tx, clock)
        grant_created = await _ensure_platform_grant(tx, settings.platform_admin_group)
        key = await SigningKeys(uow, clock, settings.key_overlap).ensure_current(tx)
        reconciled = await Reconciler(clock, BOOTSTRAP_ACTOR).run(tx, settings.organizations)
        return BootstrapResult(base_created, grant_created, key is not None, reconciled)


async def _ensure_base_schema(tx: Transaction, clock: Clock) -> bool:
    if await tx.schemas.latest(None, BASE_SCHEMA_NAME) is not None:
        return False
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
    return True


async def _ensure_platform_grant(tx: Transaction, group: str) -> bool:
    granted = await tx.grants.groups_for_scope(PLATFORM)
    current = list(granted.get(Role.PLATFORM_ADMIN, []))
    if group in current:
        return False
    await tx.grants.replace(PLATFORM, Role.PLATFORM_ADMIN, [*current, group], BOOTSTRAP_ACTOR)
    return True
