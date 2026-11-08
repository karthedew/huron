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
    actor,
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
    await lake.grants.set_organization_role(PLATFORM_ADMIN, "geo", Role.ORG_ADMIN, ["geo-admins"])
    with pytest.raises(Forbidden):
        await lake.organizations.delete(
            ORG_ADMIN.__class__("x", "x", frozenset({"geo-admins"})), "geo"
        )
    assert await lake.organizations.delete(PLATFORM_ADMIN, "geo") == "geo"
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
    groups = await lake.grants.organization_groups(PLATFORM_ADMIN, "helio")
    assert groups.org_admin == ("helio-org-admins",)
    with pytest.raises(Forbidden):
        await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.ORG_ADMIN, ["x"])
    change = await lake.grants.set_organization_role(
        PLATFORM_ADMIN, "helio", Role.ORG_ADMIN, ["new-admins"]
    )
    assert change.removed == ["helio-org-admins"]
    actions = [e.action for e in seeded.store.state.audit]
    assert Action.ORGANIZATION_REVOKE in actions


async def test_organization_groups_are_read_with_organization_read_there(seeded: World) -> None:
    lake = seeded.lake
    groups = await lake.grants.organization_groups(ORG_ADMIN, "helio")
    assert groups.as_dict() == {
        "org_admin": ["helio-org-admins"],
        "catalog_admin": [],
        "contributor": [],
        "reader": [],
    }
    with pytest.raises(Forbidden):
        await lake.grants.organization_groups(READER, "helio")
    with pytest.raises(NotFound):
        await lake.grants.organization_groups(STRANGER, "helio")


async def test_organization_wide_catalog_roles_need_org_admin(seeded: World) -> None:
    lake = seeded.lake
    change = await lake.grants.set_organization_role(
        ORG_ADMIN, "helio", Role.CATALOG_ADMIN, ["helio-wide-admins", "helio-wide-admins"]
    )
    assert (change.groups, change.added, change.removed) == (
        ["helio-wide-admins"],
        ["helio-wide-admins"],
        [],
    )
    wide_admin = actor("gina", "helio-wide-admins")
    for role in (Role.CONTRIBUTOR, Role.READER, Role.CATALOG_ADMIN):
        with pytest.raises(Forbidden) as raised:
            await lake.grants.set_organization_role(wide_admin, "helio", role, ["x"])
        assert raised.value.context["privilege"] == "CATALOG_GRANT_ADMIN"
    with pytest.raises(Forbidden):
        await lake.grants.set_organization_role(wide_admin, "helio", Role.ORG_ADMIN, ["x"])
    added = await lake.grants.set_catalog_role(
        wide_admin, "heliophysics", Role.READER, ["helio-readers", "guests"]
    )
    assert added.added == ["guests"]
    with pytest.raises(Forbidden):
        await lake.grants.set_catalog_role(wide_admin, "heliophysics", Role.CATALOG_ADMIN, ["x"])
    with pytest.raises(GrantInvalid):
        await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.PLATFORM_ADMIN, ["x"])
    with pytest.raises(GrantInvalid):
        await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.READER, [" pad"])
    entries = [e for e in seeded.store.state.audit if e.action is Action.ORGANIZATION_GRANT]
    assert entries[-1].detail == {"role": "catalog_admin", "ldap_group": "helio-wide-admins"}


async def test_organization_wide_roles_hold_in_every_catalog_of_the_organization(
    seeded: World,
) -> None:
    lake = seeded.lake
    await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.READER, ["helio-everyone"])
    await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.CONTRIBUTOR, ["helio-writers"])
    await lake.catalogs.create(ORG_ADMIN, "helio", "later")
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    await lake.catalogs.create(PLATFORM_ADMIN, "geo", "rocks")
    everyone = actor("hal", "helio-everyone")
    names = [v.catalog.name for v in (await lake.catalogs.list(everyone)).items]
    assert names == ["heliophysics", "later"]
    assert (await lake.organizations.get(everyone, "helio")).catalog_count == 2
    with pytest.raises(NotFound):
        await lake.catalogs.get(everyone, "rocks")
    writer = actor("ivy", "helio-writers")
    await lake.namespaces.create(ORG_ADMIN, "later", "", "runs", True)
    draft = await lake.collections.create(writer, "later", "runs", "one")
    assert draft.collection.name == "one"
    with pytest.raises(Forbidden):
        await lake.namespaces.create(writer, "later", "", "more", True)
    sources = await lake.grants.catalog_grant_sources(everyone, "later")
    rows = {(str(s.role), s.ldap_group, str(s.scope.type)) for s in sources}
    assert {
        ("reader", "helio-everyone", "organization"),
        ("contributor", "helio-writers", "organization"),
    } <= rows


async def test_catalog_grants_add_to_the_inherited_ones(seeded: World) -> None:
    lake = seeded.lake
    await lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.READER, ["helio-readers"])
    await lake.grants.set_catalog_role(ORG_ADMIN, "heliophysics", Role.READER, [])
    readers = await lake.grants.catalog_grant_sources(READER, "heliophysics")
    assert [(s.ldap_group, str(s.scope.type)) for s in readers if s.role is Role.READER] == [
        ("helio-readers", "organization")
    ]
    await lake.grants.set_catalog_role(ORG_ADMIN, "heliophysics", Role.READER, ["helio-readers"])
    sources = await lake.grants.catalog_grant_sources(READER, "heliophysics")
    rows = [(str(s.role), s.ldap_group, str(s.scope.type)) for s in sources]
    assert rows == [
        ("platform_admin", PLATFORM_GROUP, "platform"),
        ("org_admin", "helio-org-admins", "organization"),
        ("catalog_admin", "helio-catalog-admins", "catalog"),
        ("contributor", "helio-contributors", "catalog"),
        ("reader", "helio-readers", "organization"),
        ("reader", "helio-readers", "catalog"),
    ]
    with pytest.raises(NotFound):
        await lake.grants.catalog_grant_sources(STRANGER, "heliophysics")


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
