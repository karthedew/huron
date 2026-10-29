"""Organizations and grant administration."""

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.errors import NameTaken
from huron.core.lake.organizations.errors import OrganizationNotEmpty
from huron.core.security.rbac import GrantInvalid, Role
from huron.pkg.errors import Forbidden, NotFound
from huron.pkg.paging import InvalidCursor
from huron.schema.naming import NamingError
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    PLATFORM_ADMIN,
    PLATFORM_GROUP,
    READER,
    STRANGER,
    World,
)


async def test_platform_admin_creates_and_lists_organizations(world: World) -> None:
    view = await world.lake.organizations.create(PLATFORM_ADMIN, "helio", "", "desc")
    assert view.organization.display_name == "helio"
    assert view.as_dict()["catalog_count"] == 0
    await world.lake.organizations.create(PLATFORM_ADMIN, "geo")
    page = await world.lake.organizations.list(PLATFORM_ADMIN, limit=1)
    assert [v.organization.name for v in page.items] == ["geo"]
    rest = await world.lake.organizations.list(PLATFORM_ADMIN, cursor=page.next_cursor)
    assert [v.organization.name for v in rest.items] == ["helio"]
    assert rest.next_cursor is None
    actions = [entry.action for entry in world.store.state.audit]
    assert actions.count(Action.ORGANIZATION_CREATE) == 2


async def test_only_platform_admins_create_organizations(world: World) -> None:
    with pytest.raises(Forbidden):
        await world.lake.organizations.create(ORG_ADMIN, "helio")


async def test_names_are_checked_and_unique(world: World) -> None:
    with pytest.raises(NamingError):
        await world.lake.organizations.create(PLATFORM_ADMIN, "Bad Name")
    await world.lake.organizations.create(PLATFORM_ADMIN, "helio")
    with pytest.raises(NameTaken):
        await world.lake.organizations.create(PLATFORM_ADMIN, "helio")


async def test_hidden_organizations_are_not_found(seeded: World) -> None:
    lake = seeded.lake
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    with pytest.raises(NotFound):
        await lake.organizations.get(READER, "geo")
    assert (await lake.organizations.get(READER, "helio")).catalog_count == 1
    names = [v.organization.name for v in (await lake.organizations.list(READER)).items]
    assert names == ["helio"]
    assert (await lake.organizations.list(STRANGER)).items == ()
    with pytest.raises(InvalidCursor):
        await lake.organizations.list(READER, cursor="garbage")


async def test_organizations_with_catalogs_cannot_be_deleted(seeded: World) -> None:
    lake = seeded.lake
    with pytest.raises(OrganizationNotEmpty):
        await lake.organizations.delete(PLATFORM_ADMIN, "helio")
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    await lake.grants.set_org_admins(PLATFORM_ADMIN, "geo", ["geo-admins"])
    with pytest.raises(Forbidden):
        await lake.organizations.delete(
            ORG_ADMIN.__class__("x", "x", frozenset({"geo-admins"})), "geo"
        )
    await lake.organizations.delete(PLATFORM_ADMIN, "geo")
    with pytest.raises(NotFound):
        await lake.organizations.get(PLATFORM_ADMIN, "geo")
    assert not [key for key in seeded.store.state.grants if key[2] == "geo-admins"]


async def test_platform_admin_group_cannot_be_removed(world: World) -> None:
    lake = world.lake
    assert await lake.grants.platform_admins(PLATFORM_ADMIN) == [PLATFORM_GROUP]
    with pytest.raises(GrantInvalid) as raised:
        await lake.grants.set_platform_admins(PLATFORM_ADMIN, ["someone-else"])
    assert raised.value.status == 422
    change = await lake.grants.set_platform_admins(PLATFORM_ADMIN, [PLATFORM_GROUP, "ops"])
    assert change.added == ["ops"] and change.removed == []
    assert change.as_dict()["ldap_groups"] == ["huron-platform-admins", "ops"]
    actions = [e.action for e in world.store.state.audit]
    assert Action.PLATFORM_GRANT in actions


async def test_organization_admin_groups_are_platform_managed(seeded: World) -> None:
    lake = seeded.lake
    assert await lake.grants.org_admins(PLATFORM_ADMIN, "helio") == ["helio-org-admins"]
    with pytest.raises(Forbidden):
        await lake.grants.org_admins(ORG_ADMIN, "helio")
    change = await lake.grants.set_org_admins(PLATFORM_ADMIN, "helio", ["new-admins"])
    assert change.removed == ["helio-org-admins"]
    actions = [e.action for e in seeded.store.state.audit]
    assert Action.ORGANIZATION_REVOKE in actions


async def test_catalog_roles_need_the_right_privilege(seeded: World) -> None:
    lake = seeded.lake
    with pytest.raises(Forbidden):
        await lake.grants.set_catalog_role(CATALOG_ADMIN, "heliophysics", Role.CATALOG_ADMIN, ["x"])
    with pytest.raises(Forbidden):
        await lake.grants.set_catalog_role(CONTRIBUTOR, "heliophysics", Role.READER, ["x"])
    with pytest.raises(GrantInvalid):
        await lake.grants.set_catalog_role(ORG_ADMIN, "heliophysics", Role.ORG_ADMIN, ["x"])
    with pytest.raises(GrantInvalid):
        await lake.grants.set_catalog_role(ORG_ADMIN, "heliophysics", Role.READER, [" pad"])
    change = await lake.grants.set_catalog_role(
        CATALOG_ADMIN, "heliophysics", Role.READER, ["helio-readers", "guests"]
    )
    assert change.added == ["guests"]


async def test_effective_groups_include_platform_and_organization(seeded: World) -> None:
    groups = await seeded.lake.grants.catalog_groups(READER, "heliophysics")
    assert groups.platform_admin == (PLATFORM_GROUP,)
    assert groups.org_admin == ("helio-org-admins",)
    assert groups.contributor == ("helio-contributors",)
    with pytest.raises(NotFound):
        await seeded.lake.grants.catalog_groups(STRANGER, "heliophysics")


async def test_an_unprivileged_caller_is_refused_before_the_platform_groups_are_checked(
    seeded: World,
) -> None:
    with pytest.raises(Forbidden):
        await seeded.lake.grants.set_platform_admins(READER, [])


async def test_catalog_counts_include_only_catalogs_the_caller_can_see(seeded: World) -> None:
    lake = seeded.lake
    await lake.catalogs.create(ORG_ADMIN, "helio", "hidden")
    assert (await lake.organizations.get(ORG_ADMIN, "helio")).catalog_count == 2
    assert (await lake.organizations.get(PLATFORM_ADMIN, "helio")).catalog_count == 2
    assert (await lake.organizations.get(READER, "helio")).catalog_count == 1
    listed = await lake.organizations.list(READER)
    assert [view.catalog_count for view in listed.items] == [1]
