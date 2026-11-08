"""Roles, privileges, grants and the authorizer."""

import uuid

import pytest

from huron.core.security.rbac import (
    CATALOG_ROLES,
    ORGANIZATION_ROLES,
    PLATFORM,
    ROLE_PRIVILEGES,
    Actor,
    Authorizer,
    Grant,
    GrantInvalid,
    GrantSource,
    Privilege,
    Role,
    Scope,
    ScopeType,
    check_grant,
    scope_types_of,
)
from huron.pkg.errors import Forbidden
from tests.support.rbac import FakeGrantReader

ORG_A, ORG_B = uuid.uuid4(), uuid.uuid4()
CAT_A1, CAT_A2, CAT_B1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CATALOGS = {CAT_A1: ORG_A, CAT_A2: ORG_A, CAT_B1: ORG_B}

P = Privilege
TABLE: dict[Role, set[Privilege]] = {
    Role.READER: {P.ORGANIZATION_READ, P.CATALOG_READ, P.COLLECTION_READ, P.AUDIT_READ},
}
TABLE[Role.CONTRIBUTOR] = TABLE[Role.READER] | {
    P.COLLECTION_CREATE,
    P.COLLECTION_WRITE_METADATA,
    P.COLLECTION_WRITE_FILES,
    P.COLLECTION_DELETE_OWN,
}
TABLE[Role.CATALOG_ADMIN] = TABLE[Role.CONTRIBUTOR] | {
    P.CATALOG_GRANT_MEMBER,
    P.SCHEMA_ASSIGN,
    P.NAMESPACE_CREATE,
    P.NAMESPACE_DELETE,
    P.NAMESPACE_CONFIGURE,
    P.COLLECTION_DELETE_ANY,
}
TABLE[Role.ORG_ADMIN] = TABLE[Role.CATALOG_ADMIN] | {
    P.CATALOG_CREATE,
    P.CATALOG_DELETE,
    P.CATALOG_GRANT_ADMIN,
    P.SCHEMA_PUBLISH,
}
TABLE[Role.PLATFORM_ADMIN] = set(Privilege)


def actor(*groups: str) -> Actor:
    return Actor("user", "User", frozenset(groups))


@pytest.fixture
def authorizer() -> Authorizer:
    return Authorizer(
        FakeGrantReader(
            [
                Grant(PLATFORM, Role.PLATFORM_ADMIN, "platform"),
                Grant(Scope.organization(ORG_A), Role.ORG_ADMIN, "org-a-admins"),
                Grant(Scope.catalog(CAT_A1), Role.CATALOG_ADMIN, "a1-admins"),
                Grant(Scope.catalog(CAT_A1), Role.CONTRIBUTOR, "a1-contrib"),
                Grant(Scope.catalog(CAT_A1), Role.READER, "a1-readers"),
                Grant(Scope.catalog(CAT_B1), Role.READER, "b1-readers"),
                Grant(Scope.organization(ORG_A), Role.READER, "a-everyone"),
                Grant(Scope.organization(ORG_A), Role.READER, "a-shared"),
                Grant(Scope.catalog(CAT_A1), Role.READER, "a-shared"),
                Grant(Scope.organization(ORG_A), Role.CONTRIBUTOR, "a-writers"),
                Grant(Scope.organization(ORG_A), Role.CATALOG_ADMIN, "a-curators"),
            ],
            CATALOGS,
        )
    )


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("privilege", list(Privilege))
def test_privilege_table_matches_the_plan(role: Role, privilege: Privilege) -> None:
    assert (privilege in ROLE_PRIVILEGES[role]) == (privilege in TABLE[role])


def test_roles_have_fixed_scope_types() -> None:
    assert scope_types_of(Role.PLATFORM_ADMIN) == {ScopeType.PLATFORM}
    assert scope_types_of(Role.ORG_ADMIN) == {ScopeType.ORGANIZATION}
    both = {ScopeType.ORGANIZATION, ScopeType.CATALOG}
    assert all(scope_types_of(role) == both for role in CATALOG_ROLES)
    assert (Role.ORG_ADMIN, *CATALOG_ROLES) == ORGANIZATION_ROLES


@pytest.mark.parametrize(
    "grant",
    [
        Grant(Scope.catalog(CAT_A1), Role.ORG_ADMIN, "g"),
        Grant(PLATFORM, Role.READER, "g"),
        Grant(Scope.organization(ORG_A), Role.PLATFORM_ADMIN, "g"),
        Grant(Scope(ScopeType.PLATFORM, ORG_A), Role.PLATFORM_ADMIN, "g"),
        Grant(Scope(ScopeType.CATALOG), Role.READER, "g"),
        Grant(Scope.catalog(CAT_A1), Role.READER, ""),
        Grant(Scope.catalog(CAT_A1), Role.READER, " padded"),
    ],
)
def test_misplaced_grants_are_refused(grant: Grant) -> None:
    with pytest.raises(GrantInvalid):
        check_grant(grant)


def test_well_formed_grants_are_accepted() -> None:
    grant = Grant(Scope.catalog(CAT_A1), Role.CONTRIBUTOR, "a1-contrib")
    assert check_grant(grant) is grant
    for role in ORGANIZATION_ROLES:
        organization_wide = Grant(Scope.organization(ORG_A), role, "g")
        assert check_grant(organization_wide) is organization_wide


def test_a_misplaced_catalog_role_names_both_scopes() -> None:
    with pytest.raises(GrantInvalid, match="organization or catalog scope"):
        check_grant(Grant(PLATFORM, Role.CONTRIBUTOR, "g"))


async def test_contributor_holds_nothing_on_another_catalog(authorizer: Authorizer) -> None:
    contributor = actor("a1-contrib")
    assert await authorizer.holds(contributor, P.COLLECTION_CREATE, Scope.catalog(CAT_A1))
    assert not await authorizer.holds(contributor, P.COLLECTION_READ, Scope.catalog(CAT_A2))
    assert not await authorizer.holds(contributor, P.NAMESPACE_CREATE, Scope.catalog(CAT_A1))


async def test_organization_admin_encloses_its_catalogs_only(authorizer: Authorizer) -> None:
    admin = actor("org-a-admins")
    assert await authorizer.holds(admin, P.NAMESPACE_CREATE, Scope.catalog(CAT_A2))
    assert await authorizer.holds(admin, P.CATALOG_CREATE, Scope.organization(ORG_A))
    assert not await authorizer.holds(admin, P.CATALOG_READ, Scope.catalog(CAT_B1))
    assert not await authorizer.holds(admin, P.ORGANIZATION_CREATE, PLATFORM)


async def test_platform_admin_encloses_everything(authorizer: Authorizer) -> None:
    admin = actor("platform")
    for scope in (PLATFORM, Scope.organization(ORG_B), Scope.catalog(CAT_B1)):
        assert await authorizer.holds(admin, P.COLLECTION_DELETE_ANY, scope)
    visible = await authorizer.visibility(admin)
    assert visible.everything


async def test_unknown_groups_grant_nothing(authorizer: Authorizer) -> None:
    stranger = actor("nobody", "also-nobody")
    assert not await authorizer.holds(stranger, P.CATALOG_READ, Scope.catalog(CAT_A1))
    assert not await authorizer.can_see_catalog(stranger, CAT_A1)
    with pytest.raises(Forbidden) as raised:
        await authorizer.require(stranger, P.CATALOG_READ, Scope.catalog(CAT_A1))
    assert raised.value.context == {"privilege": "CATALOG_READ", "scope": "catalog"}


async def test_require_passes_for_a_held_privilege(authorizer: Authorizer) -> None:
    await authorizer.require(actor("a1-admins"), P.SCHEMA_ASSIGN, Scope.catalog(CAT_A1))


async def test_visibility_reaches_the_organization_of_a_granted_catalog(
    authorizer: Authorizer,
) -> None:
    reader = actor("b1-readers", "a1-readers")
    visible = await authorizer.visibility(reader)
    assert not visible.everything
    assert visible.catalog_ids == {CAT_B1, CAT_A1}
    assert visible.organization_ids == {ORG_A, ORG_B}
    assert await authorizer.can_see_organization(reader, ORG_B)
    assert await authorizer.can_see_catalog(reader, CAT_A1)
    assert not await authorizer.can_see_catalog(reader, CAT_A2)
    org_admin = actor("org-a-admins")
    assert (await authorizer.visibility(org_admin)).organization_ids == {ORG_A}
    assert await authorizer.can_see_catalog(org_admin, CAT_A2)
    assert not await authorizer.can_see_organization(actor("x"), ORG_A)


async def test_roles_are_cached_per_group_set(authorizer: Authorizer) -> None:
    reader = actor("a1-readers")
    first = await authorizer.roles_for(reader)
    assert await authorizer.roles_for(reader) is first


async def test_organization_wide_catalog_roles_hold_in_every_catalog_of_it(
    authorizer: Authorizer,
) -> None:
    writer = actor("a-writers")
    for catalog in (CAT_A1, CAT_A2):
        assert await authorizer.holds(writer, P.COLLECTION_CREATE, Scope.catalog(catalog))
        assert not await authorizer.holds(writer, P.NAMESPACE_CREATE, Scope.catalog(catalog))
    assert not await authorizer.holds(writer, P.COLLECTION_READ, Scope.catalog(CAT_B1))
    curator = actor("a-curators")
    assert await authorizer.holds(curator, P.NAMESPACE_CREATE, Scope.catalog(CAT_A2))
    assert await authorizer.holds(curator, P.CATALOG_GRANT_MEMBER, Scope.catalog(CAT_A2))
    assert not await authorizer.holds(curator, P.CATALOG_GRANT_ADMIN, Scope.organization(ORG_A))
    assert not await authorizer.holds(curator, P.CATALOG_CREATE, Scope.organization(ORG_A))
    everyone = actor("a-everyone")
    visible = await authorizer.visibility(everyone)
    assert visible.managed_organization_ids == {ORG_A} == visible.organization_ids
    assert visible.catalog_ids == frozenset()
    assert await authorizer.can_see_catalog(everyone, CAT_A2)
    assert not await authorizer.can_see_catalog(everyone, CAT_B1)
    assert await authorizer.holds(everyone, P.ORGANIZATION_READ, Scope.organization(ORG_A))


async def test_grant_sources_name_the_scope_of_each_grant(authorizer: Authorizer) -> None:
    sources = await authorizer.grant_sources(Scope.catalog(CAT_A1))
    org_a, cat_a1 = Scope.organization(ORG_A), Scope.catalog(CAT_A1)
    assert sources == [
        GrantSource(Role.PLATFORM_ADMIN, "platform", PLATFORM),
        GrantSource(Role.ORG_ADMIN, "org-a-admins", org_a),
        GrantSource(Role.CATALOG_ADMIN, "a-curators", org_a),
        GrantSource(Role.CATALOG_ADMIN, "a1-admins", cat_a1),
        GrantSource(Role.CONTRIBUTOR, "a-writers", org_a),
        GrantSource(Role.CONTRIBUTOR, "a1-contrib", cat_a1),
        GrantSource(Role.READER, "a-everyone", org_a),
        GrantSource(Role.READER, "a-shared", org_a),
        GrantSource(Role.READER, "a-shared", cat_a1),
        GrantSource(Role.READER, "a1-readers", cat_a1),
    ]
    assert await authorizer.grant_sources(Scope.catalog(CAT_B1)) == [
        GrantSource(Role.PLATFORM_ADMIN, "platform", PLATFORM),
        GrantSource(Role.READER, "b1-readers", Scope.catalog(CAT_B1)),
    ]
