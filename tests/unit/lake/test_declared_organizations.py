"""Declared organizations: their rules, the startup reconcile and the managed-mode guards."""

from dataclasses import replace

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.bootstrap import BOOTSTRAP_ACTOR, LakeSettings, bootstrap, build_lake
from huron.core.lake.organizations.declarations import (
    UNMANAGED,
    Declarations,
    DeclaredOrganization,
)
from huron.core.lake.organizations.errors import (
    DeclarationInvalid,
    OrganizationDeclared,
    OrganizationNotEmpty,
    OrganizationsManaged,
)
from huron.core.lake.organizations.models import OrganizationGroups
from huron.core.lake.organizations.reconcile import (
    Reconciler,
    Reconciliation,
    UndeclaredOrganization,
)
from huron.core.security.rbac import Role, Scope
from huron.pkg.errors import Forbidden
from huron.schema.naming import NamingError
from tests.support.lake import ORG_ADMIN, PLATFORM_ADMIN, SETTINGS, World, actor, make_world

HELIO = DeclaredOrganization(
    "helio",
    "Heliophysics",
    "Sun and wind",
    OrganizationGroups(org_admin=("helio-org-admins",)),
    "/data1/huron",
    "nfs1:/x",
)
GEO = DeclaredOrganization(
    "geo", groups=OrganizationGroups(org_admin=("geo-org-admins",)), root="/data2/huron"
)
FULL = OrganizationGroups(
    org_admin=("helio-org-admins",),
    catalog_admin=("helio-catalog-admins",),
    contributor=("helio-contributors",),
    reader=("helio-readers",),
)


def managed(*entries: DeclaredOrganization) -> LakeSettings:
    return replace(SETTINGS, organizations=Declarations.of(entries))


async def org_groups(world: World, name: str, role: Role = Role.ORG_ADMIN) -> list[str]:
    async with world.store.transaction() as tx:
        found = await tx.organizations.get_by_name(name)
        assert found is not None
        granted = await tx.grants.groups_for_scope(Scope.organization(found.id))
        return sorted(granted.get(role, []))


# The declaration values


def test_a_declaration_has_a_path_under_its_root_and_a_title() -> None:
    assert HELIO.path == "/data1/huron/helio"
    assert HELIO.title == "Heliophysics"
    assert GEO.title == "geo"
    assert DeclaredOrganization("bare").path is None
    assert DeclaredOrganization("top", root="/").path == "/top"
    assert HELIO.as_dict() == {
        "declared": True,
        "root": "/data1/huron",
        "path": "/data1/huron/helio",
        "export": "nfs1:/x",
    }
    assert DeclaredOrganization("bare").as_dict()["export"] is None


def test_role_groups_are_deduplicated_and_sorted() -> None:
    groups = OrganizationGroups(org_admin=("b", "a", "b"), reader=("r", "r"))
    declared = DeclaredOrganization("helio", groups=groups)
    assert declared.groups.org_admin == ("a", "b")
    assert declared.groups.reader == ("r",)
    assert declared.groups.catalog_admin == () == declared.groups.contributor
    assert DeclaredOrganization("bare").groups == OrganizationGroups()


def test_role_groups_read_per_role_and_render_for_the_api() -> None:
    assert [role for role, _ in FULL.items()] == [
        Role.ORG_ADMIN,
        Role.CATALOG_ADMIN,
        Role.CONTRIBUTOR,
        Role.READER,
    ]
    assert FULL.groups(Role.READER) == ("helio-readers",)
    with pytest.raises(KeyError):
        FULL.groups(Role.PLATFORM_ADMIN)
    assert FULL.as_dict()["contributor"] == ["helio-contributors"]
    granted = {Role.PLATFORM_ADMIN: ["p"], Role.READER: ["b", "a"]}
    assert OrganizationGroups.of(granted) == OrganizationGroups(reader=("a", "b"))
    assert OrganizationGroups.of({}) == OrganizationGroups()


@pytest.mark.parametrize("role", ["org_admin", "catalog_admin", "contributor", "reader"])
@pytest.mark.parametrize("group", ["", " padded", "padded "])
def test_blank_or_padded_role_groups_are_refused(role: str, group: str) -> None:
    with pytest.raises(DeclarationInvalid) as raised:
        DeclaredOrganization("helio", groups=OrganizationGroups(**{role: (group,)}))
    assert f"groups.{role}" in raised.value.message
    assert raised.value.context["role"] == role


def test_a_declared_name_follows_the_segment_rules() -> None:
    with pytest.raises(NamingError):
        DeclaredOrganization("Bad Name")


@pytest.mark.parametrize(
    "root",
    ["relative/path", "/data1/huron/", "/data1/../etc", "/data1/./huron", "//host/x", "/a\nb", ""],
)
def test_a_root_must_be_absolute_and_normalized(root: str) -> None:
    with pytest.raises(DeclarationInvalid):
        DeclaredOrganization("helio", root=root)


def test_declarations_refuse_a_name_declared_twice() -> None:
    with pytest.raises(DeclarationInvalid):
        Declarations.of([HELIO, DeclaredOrganization("helio")])


def test_declarations_look_up_by_name_and_know_their_mode() -> None:
    declarations = Declarations.of([HELIO, GEO])
    assert declarations.managed and not UNMANAGED.managed
    assert Declarations.of([]).managed
    assert Declarations.of(None) == UNMANAGED
    assert [d.name for d in declarations] == ["helio", "geo"]
    assert list(UNMANAGED) == []
    assert declarations.get("geo") == GEO and declarations.get("nope") is None
    assert declarations.share_root("helio") == "/data1/huron"
    assert declarations.share_root("nope") is None
    assert Declarations.of([DeclaredOrganization("bare")]).share_root("bare") is None


def test_the_guards_refuse_only_in_managed_mode_and_for_declared_names() -> None:
    UNMANAGED.require_unmanaged()
    UNMANAGED.require_undeclared("helio", "why")
    declarations = Declarations.of([HELIO])
    with pytest.raises(OrganizationsManaged) as managed_error:
        declarations.require_unmanaged()
    assert managed_error.value.status == 409
    declarations.require_undeclared("geo", "why")
    with pytest.raises(OrganizationDeclared) as declared_error:
        declarations.require_undeclared("helio", "why")
    assert declared_error.value.context == {"organization": "helio"}
    assert declared_error.value.status == 409


# The reconcile at bootstrap


async def test_bootstrap_creates_declared_organizations_with_their_admins() -> None:
    world = await make_world(managed(HELIO, GEO))
    view = await world.lake.organizations.get(PLATFORM_ADMIN, "helio")
    organization = view.organization
    assert (organization.display_name, organization.description) == ("Heliophysics", "Sun and wind")
    assert (organization.version, organization.created_by) == (1, BOOTSTRAP_ACTOR)
    geo = await world.lake.organizations.get(PLATFORM_ADMIN, "geo")
    assert geo.organization.display_name == "geo"
    assert await org_groups(world, "helio") == ["helio-org-admins"]
    audit = [(e.action, e.actor, e.detail) for e in world.store.state.audit]
    assert (Action.ORGANIZATION_CREATE, BOOTSTRAP_ACTOR, {"name": "helio"}) in audit
    assert (
        Action.ORGANIZATION_GRANT,
        BOOTSTRAP_ACTOR,
        {"role": "org_admin", "ldap_group": "geo-org-admins"},
    ) in audit
    assert len(audit) == 4


async def test_a_second_bootstrap_writes_nothing() -> None:
    settings = managed(HELIO, GEO)
    world = await make_world(settings)
    before = world.store.state.copy()
    again = await bootstrap(world.store, world.clock, settings)
    assert again.organizations == Reconciliation()
    assert not again.organizations.changed
    assert world.store.state.audit == before.audit
    assert world.store.state.organizations == before.organizations
    assert world.store.state.grants == before.grants


async def test_bootstrap_updates_changed_text_and_bumps_the_version() -> None:
    world = await make_world(managed(HELIO))
    changed = replace(HELIO, display_name="Helio", description="")
    result = await bootstrap(world.store, world.clock, managed(changed))
    assert result.organizations.updated == ("helio",)
    assert result.organizations.created == () == result.organizations.regranted
    organization = (await world.lake.organizations.get(PLATFORM_ADMIN, "helio")).organization
    assert (organization.display_name, organization.description, organization.version) == (
        "Helio",
        "",
        2,
    )
    last = world.store.state.audit[-1]
    assert last.action is Action.ORGANIZATION_UPDATE
    assert last.detail == {"name": "helio", "fields": ["description", "display_name"]}
    assert last.organization_id == organization.id


async def test_bootstrap_makes_the_declared_admin_groups_the_exact_set() -> None:
    world = await make_world(managed(HELIO))
    renewed = OrganizationGroups(org_admin=("new-a", "new-b"))
    await bootstrap(world.store, world.clock, managed(replace(HELIO, groups=renewed)))
    assert await org_groups(world, "helio") == ["new-a", "new-b"]
    tail = [(e.action, e.detail["ldap_group"]) for e in world.store.state.audit[-3:]]
    assert tail == [
        (Action.ORGANIZATION_GRANT, "new-a"),
        (Action.ORGANIZATION_GRANT, "new-b"),
        (Action.ORGANIZATION_REVOKE, "helio-org-admins"),
    ]
    emptied = replace(HELIO, groups=OrganizationGroups())
    result = await bootstrap(world.store, world.clock, managed(emptied))
    assert result.organizations.regranted == ("helio",)
    assert await org_groups(world, "helio") == []


async def test_bootstrap_sets_every_organization_role_exactly() -> None:
    world = await make_world(managed(replace(HELIO, groups=FULL)))
    for role, groups in FULL.items():
        assert await org_groups(world, "helio", role) == list(groups)
    granted = [e.detail for e in world.store.state.audit if e.action is Action.ORGANIZATION_GRANT]
    assert {"role": "reader", "ldap_group": "helio-readers"} in granted
    assert {"role": "catalog_admin", "ldap_group": "helio-catalog-admins"} in granted
    before = list(world.store.state.audit)
    again = await bootstrap(world.store, world.clock, managed(replace(HELIO, groups=FULL)))
    assert not again.organizations.changed and world.store.state.audit == before
    narrowed = replace(FULL, contributor=(), reader=("helio-everyone",))
    result = await bootstrap(world.store, world.clock, managed(replace(HELIO, groups=narrowed)))
    assert result.organizations.regranted == ("helio",)
    assert await org_groups(world, "helio", Role.CONTRIBUTOR) == []
    assert await org_groups(world, "helio", Role.READER) == ["helio-everyone"]
    assert await org_groups(world, "helio", Role.ORG_ADMIN) == ["helio-org-admins"]
    tail = [(e.action, e.detail) for e in world.store.state.audit[len(before) :]]
    assert tail == [
        (Action.ORGANIZATION_REVOKE, {"role": "contributor", "ldap_group": "helio-contributors"}),
        (Action.ORGANIZATION_GRANT, {"role": "reader", "ldap_group": "helio-everyone"}),
        (Action.ORGANIZATION_REVOKE, {"role": "reader", "ldap_group": "helio-readers"}),
    ]


async def test_every_catalog_of_a_declared_organization_inherits_its_role_groups() -> None:
    settings = managed(replace(HELIO, groups=FULL))
    world = await make_world(settings)
    await world.lake.catalogs.create(PLATFORM_ADMIN, "helio", "first")
    await world.lake.catalogs.create(PLATFORM_ADMIN, "helio", "second")
    reader = actor("erin", "helio-readers")
    names = [v.catalog.name for v in (await world.lake.catalogs.list(reader)).items]
    assert names == ["first", "second"]
    groups = await world.lake.grants.catalog_groups(reader, "second")
    assert (groups.catalog_admin, groups.contributor, groups.reader) == (
        ("helio-catalog-admins",),
        ("helio-contributors",),
        ("helio-readers",),
    )
    await world.lake.grants.set_catalog_role(PLATFORM_ADMIN, "first", Role.READER, ["guests"])
    sources = await world.lake.grants.catalog_grant_sources(reader, "first")
    readers = [(s.ldap_group, str(s.scope.type)) for s in sources if s.role is Role.READER]
    assert readers == [("guests", "catalog"), ("helio-readers", "organization")]


async def test_bootstrap_adopts_an_existing_organization_by_name() -> None:
    world = await make_world()
    await world.lake.organizations.create(PLATFORM_ADMIN, "helio", "Heliophysics", "Sun and wind")
    await world.lake.grants.set_organization_role(
        PLATFORM_ADMIN, "helio", Role.ORG_ADMIN, ["old-admins"]
    )
    result = await bootstrap(world.store, world.clock, managed(HELIO))
    assert result.organizations == Reconciliation(regranted=("helio",))
    assert await org_groups(world, "helio") == ["helio-org-admins"]


async def test_undeclared_organizations_are_reported_and_kept() -> None:
    world = await make_world()
    await world.lake.organizations.create(PLATFORM_ADMIN, "old")
    await world.lake.grants.set_organization_role(
        PLATFORM_ADMIN, "old", Role.ORG_ADMIN, ["helio-org-admins"]
    )
    await world.lake.catalogs.create(ORG_ADMIN, "old", "oldcat")
    result = await bootstrap(world.store, world.clock, managed(HELIO))
    assert result.organizations.undeclared == (UndeclaredOrganization("old", 1),)
    assert result.organizations.created == ("helio",)
    assert (await world.lake.organizations.get(PLATFORM_ADMIN, "old")).catalog_count == 1


async def test_the_undeclared_scan_pages_through_every_organization() -> None:
    world = await make_world()
    names = [f"org{i:03d}" for i in range(501)]
    for name in names:
        await world.lake.organizations.create(PLATFORM_ADMIN, name)
    async with world.store.transaction() as tx:
        result = await Reconciler(world.clock, BOOTSTRAP_ACTOR).run(tx, Declarations.of([]))
    assert [u.name for u in result.undeclared] == names


async def test_unmanaged_bootstrap_reconciles_nothing() -> None:
    world = await make_world()
    await world.lake.organizations.create(PLATFORM_ADMIN, "helio")
    result = await bootstrap(world.store, world.clock, SETTINGS)
    assert result.organizations == Reconciliation()


# The managed-mode guards


async def test_managed_mode_refuses_to_create_organizations() -> None:
    world = await make_world(managed(HELIO))
    with pytest.raises(OrganizationsManaged):
        await world.lake.organizations.create(PLATFORM_ADMIN, "geo")
    with pytest.raises(Forbidden):
        await world.lake.organizations.create(ORG_ADMIN, "geo")


async def test_declared_organizations_cannot_be_deleted_or_regranted() -> None:
    world = await make_world(managed(HELIO))
    with pytest.raises(OrganizationDeclared):
        await world.lake.organizations.delete(PLATFORM_ADMIN, "helio")
    for role in (Role.ORG_ADMIN, Role.CATALOG_ADMIN, Role.CONTRIBUTOR, Role.READER):
        with pytest.raises(OrganizationDeclared) as raised:
            await world.lake.grants.set_organization_role(PLATFORM_ADMIN, "helio", role, ["x"])
        assert f"groups.{role}" in raised.value.message
    with pytest.raises(OrganizationDeclared):
        await world.lake.grants.set_organization_role(ORG_ADMIN, "helio", Role.READER, ["x"])
    with pytest.raises(Forbidden):
        await world.lake.organizations.delete(ORG_ADMIN, "helio")
    groups = await world.lake.grants.organization_groups(PLATFORM_ADMIN, "helio")
    assert groups == OrganizationGroups(org_admin=("helio-org-admins",))
    await world.lake.catalogs.create(ORG_ADMIN, "helio", "sun")
    change = await world.lake.grants.set_catalog_role(ORG_ADMIN, "sun", Role.READER, ["guests"])
    assert change.added == ["guests"]


async def test_undeclared_organizations_stay_editable_and_deletable_when_empty() -> None:
    world = await make_world()
    await world.lake.organizations.create(PLATFORM_ADMIN, "old")
    await world.lake.organizations.create(PLATFORM_ADMIN, "busy")
    await world.lake.grants.set_organization_role(
        PLATFORM_ADMIN, "busy", Role.ORG_ADMIN, ["helio-org-admins"]
    )
    await world.lake.catalogs.create(ORG_ADMIN, "busy", "busycat")
    settings = managed(HELIO)
    await bootstrap(world.store, world.clock, settings)
    lake = build_lake(world.store, world.clock, settings)
    change = await lake.grants.set_organization_role(
        PLATFORM_ADMIN, "old", Role.ORG_ADMIN, ["old-admins"]
    )
    assert change.added == ["old-admins"]
    readers = await lake.grants.set_organization_role(
        PLATFORM_ADMIN, "old", Role.READER, ["old-readers"]
    )
    assert readers.added == ["old-readers"]
    with pytest.raises(OrganizationNotEmpty):
        await lake.organizations.delete(PLATFORM_ADMIN, "busy")
    await lake.organizations.delete(PLATFORM_ADMIN, "old")
    names = [v.organization.name for v in (await lake.organizations.list(PLATFORM_ADMIN)).items]
    assert names == ["busy", "helio"]


async def test_views_carry_the_declaration() -> None:
    world = await make_world(managed(HELIO, GEO, DeclaredOrganization("bare")))
    rows = {
        v.organization.name: v.as_dict()
        for v in (await world.lake.organizations.list(PLATFORM_ADMIN)).items
    }
    assert {k: rows["helio"][k] for k in ("declared", "root", "path", "export")} == {
        "declared": True,
        "root": "/data1/huron",
        "path": "/data1/huron/helio",
        "export": "nfs1:/x",
    }
    assert (rows["bare"]["root"], rows["bare"]["path"], rows["bare"]["export"]) == (
        None,
        None,
        None,
    )
    plain = await make_world()
    created = await plain.lake.organizations.create(PLATFORM_ADMIN, "helio")
    assert {k: created.as_dict()[k] for k in ("declared", "root", "path", "export")} == {
        "declared": False,
        "root": None,
        "path": None,
        "export": None,
    }
