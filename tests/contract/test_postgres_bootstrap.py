"""Bootstrap over PostgreSQL: reconciling declared organizations, and replicas starting together."""

import asyncio
from dataclasses import replace

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.bootstrap import BOOTSTRAP_ACTOR, LakeSettings, bootstrap, build_lake
from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
from huron.core.lake.organizations.models import OrganizationGroups
from huron.core.lake.organizations.reconcile import Reconciliation, UndeclaredOrganization
from huron.core.metastore.postgres import PostgresStore
from huron.core.security.rbac import Role, Scope
from tests.support.clock import frozen
from tests.support.lake import PLATFORM_ADMIN, SETTINGS

pytestmark = pytest.mark.contract

HELIO = DeclaredOrganization(
    "helio",
    "Heliophysics",
    "Sun",
    OrganizationGroups(org_admin=("helio-org-admins",)),
    "/data1/huron",
)
GEO = DeclaredOrganization(
    "geo", "Geoscience", "", OrganizationGroups(org_admin=("geo-org-admins",)), "/data2/huron"
)


def managed(*entries: DeclaredOrganization) -> LakeSettings:
    return replace(SETTINGS, organizations=Declarations.of(entries))


async def audit_actions(uow: PostgresStore) -> list[str]:
    async with uow.transaction() as tx:
        rows = await tx.connection.fetch("select action from huron.audit order by id")
        return [row["action"] for row in rows]


async def org_admins(uow: PostgresStore, name: str, role: Role = Role.ORG_ADMIN) -> list[str]:
    async with uow.transaction() as tx:
        found = await tx.organizations.get_by_name(name)
        assert found is not None
        granted = await tx.grants.groups_for_scope(Scope.organization(found.id))
        return sorted(granted.get(role, []))


async def audit_count(uow: PostgresStore) -> int:
    async with uow.transaction() as tx:
        count: int = await tx.connection.fetchval("select count(*) from huron.audit")
        return count


async def test_bootstrap_reconciles_declared_organizations(uow: PostgresStore) -> None:
    clock = frozen()
    first = await bootstrap(uow, clock, managed(HELIO, GEO))
    assert first.organizations.created == ("helio", "geo")
    assert first.organizations.regranted == ("helio", "geo")
    assert await org_admins(uow, "helio") == ["helio-org-admins"]
    entries = await audit_count(uow)
    assert entries == 4

    again = await bootstrap(uow, clock, managed(HELIO, GEO))
    assert again.organizations == Reconciliation()
    assert (again.base_schema, again.platform_grant, again.signing_key) == (False, False, False)
    assert await audit_count(uow) == entries

    changed = replace(
        HELIO, display_name="Helio", groups=OrganizationGroups(org_admin=("a-admins", "b-admins"))
    )
    third = await bootstrap(uow, clock, managed(changed))
    assert third.organizations.updated == ("helio",)
    assert third.organizations.regranted == ("helio",)
    assert third.organizations.undeclared == (UndeclaredOrganization("geo", 0),)
    assert await org_admins(uow, "helio") == ["a-admins", "b-admins"]
    lake = build_lake(uow, clock, managed(changed))
    view = await lake.organizations.get(PLATFORM_ADMIN, "helio")
    assert (view.organization.display_name, view.organization.version) == ("Helio", 2)
    assert view.organization.created_by == BOOTSTRAP_ACTOR
    assert (await audit_actions(uow))[entries:] == [
        Action.ORGANIZATION_UPDATE,
        Action.ORGANIZATION_GRANT,
        Action.ORGANIZATION_GRANT,
        Action.ORGANIZATION_REVOKE,
    ]
    assert (await lake.organizations.get(PLATFORM_ADMIN, "geo")).as_dict()["declared"] is False


async def test_bootstrap_sets_the_organization_wide_catalog_roles(uow: PostgresStore) -> None:
    clock = frozen()
    groups = OrganizationGroups(
        org_admin=("helio-org-admins",),
        catalog_admin=("helio-catalog-admins",),
        contributor=("helio-contributors",),
        reader=("helio-readers",),
    )
    declared = replace(HELIO, groups=groups)
    await bootstrap(uow, clock, managed(declared))
    for role, wanted in groups.items():
        assert await org_admins(uow, "helio", role) == list(wanted)
    entries = await audit_count(uow)
    again = await bootstrap(uow, clock, managed(declared))
    assert not again.organizations.changed and await audit_count(uow) == entries
    narrowed = replace(HELIO, groups=replace(groups, contributor=(), reader=("everyone",)))
    result = await bootstrap(uow, clock, managed(narrowed))
    assert result.organizations.regranted == ("helio",)
    assert await org_admins(uow, "helio", Role.CONTRIBUTOR) == []
    assert await org_admins(uow, "helio", Role.READER) == ["everyone"]
    assert (await audit_actions(uow))[entries:] == [
        Action.ORGANIZATION_REVOKE,
        Action.ORGANIZATION_GRANT,
        Action.ORGANIZATION_REVOKE,
    ]


async def test_replicas_bootstrapping_together_do_not_race(
    uow: PostgresStore, database_url: str
) -> None:
    stores = [PostgresStore(database_url, pool_size=2) for _ in range(4)]
    for store in stores:
        await store.connect()
    try:
        clock = frozen()
        results = await asyncio.gather(
            *(bootstrap(store, clock, managed(HELIO, GEO)) for store in stores)
        )
    finally:
        for store in stores:
            await store.close()
    assert sum(r.base_schema for r in results) == 1
    assert sum(r.signing_key for r in results) == 1
    assert sum(len(r.organizations.created) for r in results) == 2
    async with uow.transaction() as tx:
        names = [o.name for o in await tx.organizations.list(None, None, 10)]
        keys = await tx.connection.fetchval("select count(*) from huron.signing_keys")
    assert names == ["geo", "helio"]
    assert keys == 1
    assert await audit_count(uow) == 4
