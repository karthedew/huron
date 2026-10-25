"""Ranked catalog grants normalize authority and expose exact refusal facts."""

from dataclasses import FrozenInstanceError
from itertools import product
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huron.core.foundation.errors import Forbidden
from huron.core.security.broker import CatalogRef, Grant, Grants, ReadableCatalogs, Role
from huron.core.security.roles import ROLES

pytestmark = pytest.mark.unit

HELIO = CatalogRef(UUID(int=1), "heliophysics")
ASTRO = CatalogRef(UUID(int=2), "astro")


def test_role_vocabulary_and_ranks() -> None:
    """The isolated ladder pins the shared vocabulary and exact rank/scope meanings."""
    assert {r.code: r.title for r in Role} == {c: d.title for c, d in ROLES.items()}
    assert [r.value for r in Role] == [10, 20, 30, 40, 50]
    assert [r for r in Role if r.catalog_scoped] == [
        Role.READER,
        Role.DEVELOPER,
        Role.PROJECT_ADMIN,
    ]
    for role in Role:
        assert Role.from_code(role.code) is role


@pytest.mark.parametrize("code", ["", "Reader", "READER", " reader", "reader ", "missing"])
def test_unknown_role_code_is_refused(code: str) -> None:
    """Role lookup is exact and reports the unknown code."""
    with pytest.raises(ValueError, match="unknown role code"):
        Role.from_code(code)


@pytest.mark.parametrize("held,minimum", list(product(Role, Role)))
def test_global_grant_applies_to_every_catalog_and_global_requirement(
    held: Role, minimum: Role
) -> None:
    """Every pair of ranks uses the same ladder globally and on unrelated catalogs."""
    grants = Grants("alice", [Grant(held, None)])
    assert grants
    assert grants.readable() == ReadableCatalogs(True, frozenset())
    for catalog in (HELIO, ASTRO, None):
        if catalog:
            assert grants.role_on(catalog) is held
        if held >= minimum:
            assert grants.require(minimum, catalog) is None
        else:
            scope = f"catalog:{catalog.name}" if catalog else "global"
            with pytest.raises(Forbidden) as caught:
                grants.require(minimum, catalog)
            assert caught.value.detail == f"{minimum.code} required on {scope} for alice"
            assert caught.value.context == {
                "subject": "alice",
                "role": minimum.code,
                "scope": scope,
                "held": held.code,
            }
            assert caught.value.status_code == 403
        assert grants.readable(minimum) == ReadableCatalogs(held >= minimum, frozenset())


def test_catalog_grants_do_not_supply_global_or_other_catalog_authority() -> None:
    """One catalog's grant neither leaks to another nor satisfies global authority."""
    grants = Grants("alice", [Grant(Role.DEVELOPER, HELIO)])
    grants.require(Role.DEVELOPER, HELIO)
    assert grants.role_on(ASTRO) is None
    assert grants.readable() == ReadableCatalogs(False, frozenset({HELIO.id}))
    for catalog, minimum in [(None, Role.ORGANIZATION_ADMIN), (ASTRO, Role.READER)]:
        with pytest.raises(Forbidden) as caught:
            grants.require(minimum, catalog)
        scope = f"catalog:{catalog.name}" if catalog else "global"
        assert caught.value.context == {
            "subject": "alice",
            "role": minimum.code,
            "scope": scope,
            "held": None,
        }
        assert caught.value.detail == f"{minimum.code} required on {scope} for alice"


def test_global_and_catalog_grants_combine_and_iterate_by_scope_then_name() -> None:
    """Catalog authority augments the global baseline with stable claim ordering."""
    global_grant = Grant(Role.READER, None)
    helio_grant = Grant(Role.PROJECT_ADMIN, HELIO)
    astro_grant = Grant(Role.DEVELOPER, ASTRO)
    grants = Grants("alice", [helio_grant, astro_grant, global_grant])
    assert tuple(grants) == (global_grant, astro_grant, helio_grant)
    assert grants.role_on(HELIO) is Role.PROJECT_ADMIN
    assert grants.role_on(CatalogRef(UUID(int=3), "other")) is Role.READER
    assert grants.readable(Role.DEVELOPER) == ReadableCatalogs(
        False, frozenset({HELIO.id, ASTRO.id})
    )
    assert grants.readable(Role.PROJECT_ADMIN) == ReadableCatalogs(False, frozenset({HELIO.id}))
    assert grants.readable(Role.ORGANIZATION_ADMIN) == ReadableCatalogs(False, frozenset())


def test_empty_grants_are_falsy_and_return_an_empty_filter() -> None:
    """Unmapped groups produce no authority, an empty filter and an exact refusal."""
    grants = Grants("nobody", ())
    assert not grants
    assert tuple(grants) == ()
    assert grants.role_on(HELIO) is None
    assert grants.readable() == ReadableCatalogs(False, frozenset())
    with pytest.raises(Forbidden) as caught:
        grants.require(Role.READER)
    assert caught.value.context == {
        "subject": "nobody",
        "role": "reader",
        "scope": "global",
        "held": None,
    }


@pytest.mark.parametrize("role", [Role.ORGANIZATION_ADMIN, Role.PLATFORM_OWNER])
def test_global_only_role_cannot_be_granted_on_a_catalog(role: Role) -> None:
    """Invalid mapping rows fail at construction instead of acquiring authority."""
    with pytest.raises(ValueError, match="global-only role"):
        Grants("alice", [Grant(role, HELIO)])


@given(st.lists(st.sampled_from(list(Role)), min_size=1))
def test_duplicate_global_scopes_keep_the_highest_role(roles: list[Role]) -> None:
    """Input order and repeated global rows do not change effective authority."""
    expected = (Grant(max(roles), None),)
    assert tuple(Grants("alice", (Grant(role, None) for role in roles))) == expected
    assert tuple(Grants("alice", (Grant(role, None) for role in reversed(roles)))) == expected


@given(st.lists(st.sampled_from([Role.READER, Role.DEVELOPER, Role.PROJECT_ADMIN]), min_size=1))
def test_duplicate_catalog_scopes_use_identity_and_highest_role(roles: list[Role]) -> None:
    """Renaming a catalog cannot fork a scope or remove its held authority."""
    renamed = CatalogRef(HELIO.id, "renamed")
    grants = Grants("alice", [Grant(role, HELIO) for role in roles])
    assert tuple(grants) == (Grant(max(roles), HELIO),)
    assert grants.role_on(renamed) is max(roles)
    duplicate = Grants("alice", [Grant(Role.READER, HELIO), Grant(Role.DEVELOPER, renamed)])
    assert tuple(duplicate) == (Grant(Role.DEVELOPER, renamed),)
    assert duplicate.role_on(HELIO) is Role.DEVELOPER
    assert duplicate.role_on(CatalogRef(ASTRO.id, HELIO.name)) is None


def test_grants_snapshot_inputs_and_values_are_frozen() -> None:
    """Mutating the source collection cannot mutate captured authority or value fields."""
    source = [Grant(Role.READER, HELIO)]
    grants = Grants("alice", source)
    source.clear()
    assert tuple(grants) == (Grant(Role.READER, HELIO),)
    for value, field in [
        (HELIO, "name"),
        (Grant(Role.READER, HELIO), "role"),
        (grants, "_subject"),
        (grants.readable(), "every"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)


def test_global_and_catalog_ranks_use_maximum_for_every_threshold() -> None:
    """Readability and authorization agree for every legal global/catalog rank pair."""
    for global_role in Role:
        for catalog_role in (Role.READER, Role.DEVELOPER, Role.PROJECT_ADMIN):
            grants = Grants("alice", [Grant(global_role, None), Grant(catalog_role, HELIO)])
            effective = max(global_role, catalog_role)
            assert grants.role_on(HELIO) is effective
            for minimum in Role:
                if effective >= minimum:
                    grants.require(minimum, HELIO)
                else:
                    with pytest.raises(Forbidden):
                        grants.require(minimum, HELIO)
                every = global_role >= minimum
                ids = frozenset({HELIO.id}) if not every and effective >= minimum else frozenset()
                assert grants.readable(minimum) == ReadableCatalogs(every, ids)


def test_global_iteration_precedes_even_an_empty_opaque_catalog_name() -> None:
    """Scope ordering is independent of opaque catalog display names."""
    catalog_grant = Grant(Role.READER, CatalogRef(HELIO.id, ""))
    global_grant = Grant(Role.READER, None)
    assert tuple(Grants("alice", [catalog_grant, global_grant])) == (global_grant, catalog_grant)
