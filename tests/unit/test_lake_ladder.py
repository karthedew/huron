"""Ranked catalog grants normalize authority and expose exact refusal facts."""

from dataclasses import FrozenInstanceError
from itertools import product
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huron.core.foundation.errors import Forbidden
from huron.core.security.broker import CatalogRef, Grant, Grants, ReadableCatalogs, Role

pytestmark = pytest.mark.unit

HELIO = CatalogRef(UUID(int=1), "heliophysics")
ASTRO = CatalogRef(UUID(int=2), "astro")


def test_role_vocabulary_and_ranks() -> None:
    """The isolated ladder pins the lake vocabulary and exact rank/scope meanings."""
    assert {r.code: r.title for r in Role} == {
        "catalog_reader": "Catalog Reader",
        "catalog_contributor": "Catalog Contributor",
        "catalog_owner": "Catalog Owner",
        "administrator": "Administrator",
    }
    assert [r.value for r in Role] == [10, 20, 30, 40]
    assert [r for r in Role if r.catalog_scoped] == [
        Role.CATALOG_READER,
        Role.CATALOG_CONTRIBUTOR,
        Role.CATALOG_OWNER,
    ]
    for role in Role:
        assert Role.from_code(role.code) is role


@pytest.mark.parametrize(
    "code",
    [
        "",
        "Catalog_Reader",
        "CATALOG_READER",
        " catalog_reader",
        "catalog_reader ",
        "missing",
        "reader",
        "developer",
        "project_admin",
        "organization_admin",
        "platform_owner",
    ],
)
def test_unknown_role_code_is_refused(code: str) -> None:
    """Role lookup is exact and reports the unknown code."""
    with pytest.raises(ValueError, match="unknown role code"):
        Role.from_code(code)


@pytest.mark.parametrize("minimum", list(Role))
def test_administrator_applies_to_every_catalog_and_organization(minimum: Role) -> None:
    """Organization Administrator satisfies every threshold in every catalog."""
    grants = Grants("alice", [Grant(Role.ADMINISTRATOR, None)])
    assert grants
    for catalog in (HELIO, ASTRO, None):
        if catalog:
            assert grants.role_on(catalog) is Role.ADMINISTRATOR
        assert grants.require(minimum, catalog) is None
    assert grants.readable(minimum) == ReadableCatalogs(True, frozenset())


@pytest.mark.parametrize("held,minimum", list(product(list(Role)[:3], Role)))
def test_catalog_authority_uses_rank_only_within_its_catalog(held: Role, minimum: Role) -> None:
    """Each catalog rank includes lower ranks, with exact refusals above its rank."""
    grants = Grants("alice", [Grant(held, HELIO)])
    if held >= minimum:
        grants.require(minimum, HELIO)
    else:
        with pytest.raises(Forbidden) as caught:
            grants.require(minimum, HELIO)
        assert caught.value.context == {
            "subject": "alice",
            "role": minimum.code,
            "scope": "catalog:heliophysics",
            "held": held.code,
        }
        assert caught.value.detail == f"{minimum.code} required on catalog:heliophysics for alice"
        assert caught.value.status_code == 403
    ids = frozenset({HELIO.id}) if held >= minimum else frozenset()
    assert grants.readable(minimum) == ReadableCatalogs(False, ids)


def test_catalog_grants_do_not_supply_organization_or_other_catalog_authority() -> None:
    """One catalog's grant neither leaks to another nor satisfies organization authority."""
    grants = Grants("alice", [Grant(Role.CATALOG_CONTRIBUTOR, HELIO)])
    grants.require(Role.CATALOG_CONTRIBUTOR, HELIO)
    assert grants.role_on(ASTRO) is None
    assert grants.readable() == ReadableCatalogs(False, frozenset({HELIO.id}))
    for catalog, minimum in [(None, Role.ADMINISTRATOR), (ASTRO, Role.CATALOG_READER)]:
        with pytest.raises(Forbidden) as caught:
            grants.require(minimum, catalog)
        scope = f"catalog:{catalog.name}" if catalog else "organization"
        assert caught.value.context == {
            "subject": "alice",
            "role": minimum.code,
            "scope": scope,
            "held": None,
        }
        assert caught.value.detail == f"{minimum.code} required on {scope} for alice"


def test_catalog_grants_combine_and_iterate_by_name_without_leaking_authority() -> None:
    """Additive catalog grants remain confined to their assigned identities."""
    helio_grant = Grant(Role.CATALOG_OWNER, HELIO)
    astro_grant = Grant(Role.CATALOG_CONTRIBUTOR, ASTRO)
    grants = Grants("alice", [helio_grant, astro_grant])
    assert tuple(grants) == (astro_grant, helio_grant)
    assert grants.role_on(HELIO) is Role.CATALOG_OWNER
    assert grants.role_on(CatalogRef(UUID(int=3), "other")) is None
    assert grants.readable(Role.CATALOG_CONTRIBUTOR) == ReadableCatalogs(
        False, frozenset({HELIO.id, ASTRO.id})
    )
    assert grants.readable(Role.CATALOG_OWNER) == ReadableCatalogs(False, frozenset({HELIO.id}))
    assert grants.readable(Role.ADMINISTRATOR) == ReadableCatalogs(False, frozenset())


def test_empty_grants_are_falsy_and_return_an_empty_filter() -> None:
    """Unmapped groups produce no authority, an empty filter and an exact refusal."""
    grants = Grants("nobody", ())
    assert not grants
    assert tuple(grants) == ()
    assert grants.role_on(HELIO) is None
    assert grants.readable() == ReadableCatalogs(False, frozenset())
    with pytest.raises(Forbidden) as caught:
        grants.require(Role.CATALOG_READER)
    assert caught.value.context == {
        "subject": "nobody",
        "role": "catalog_reader",
        "scope": "organization",
        "held": None,
    }


@pytest.mark.parametrize("role", list(Role))
def test_role_rejects_the_wrong_scope_at_grant_construction(role: Role) -> None:
    """No invalid role/scope value can be used to construct authority."""
    with pytest.raises(ValueError, match="catalog roles require a catalog"):
        Grant(role, None if role.catalog_scoped else HELIO)


@given(st.integers(min_value=1, max_value=20))
def test_duplicate_organization_scopes_normalize_to_one_administrator(count: int) -> None:
    """Repeated organization grants cannot change effective authority."""
    grant = Grant(Role.ADMINISTRATOR, None)
    assert tuple(Grants("alice", [grant] * count)) == (grant,)


@given(
    st.lists(
        st.sampled_from([Role.CATALOG_READER, Role.CATALOG_CONTRIBUTOR, Role.CATALOG_OWNER]),
        min_size=1,
    )
)
def test_duplicate_catalog_scopes_use_identity_and_highest_role(roles: list[Role]) -> None:
    """Renaming a catalog cannot fork a scope or remove its held authority."""
    renamed = CatalogRef(HELIO.id, "renamed")
    grants = Grants("alice", [Grant(role, HELIO) for role in roles])
    assert tuple(grants) == (Grant(max(roles), HELIO),)
    assert tuple(Grants("alice", [Grant(role, HELIO) for role in reversed(roles)])) == tuple(grants)
    assert grants.role_on(renamed) is max(roles)
    duplicate = Grants(
        "alice", [Grant(Role.CATALOG_READER, HELIO), Grant(Role.CATALOG_CONTRIBUTOR, renamed)]
    )
    assert tuple(duplicate) == (Grant(Role.CATALOG_CONTRIBUTOR, renamed),)
    assert duplicate.role_on(HELIO) is Role.CATALOG_CONTRIBUTOR
    assert duplicate.role_on(CatalogRef(ASTRO.id, HELIO.name)) is None


def test_grants_snapshot_inputs_and_values_are_frozen() -> None:
    """Mutating the source collection cannot mutate captured authority or value fields."""
    source = [Grant(Role.CATALOG_READER, HELIO)]
    grants = Grants("alice", source)
    source.clear()
    assert tuple(grants) == (Grant(Role.CATALOG_READER, HELIO),)
    for value, field in [
        (HELIO, "name"),
        (Grant(Role.CATALOG_READER, HELIO), "role"),
        (grants, "_subject"),
        (grants.readable(), "every"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)


@pytest.mark.parametrize(
    "catalog_role", [Role.CATALOG_READER, Role.CATALOG_CONTRIBUTOR, Role.CATALOG_OWNER]
)
def test_administrator_and_catalog_grants_retain_organization_authority(catalog_role: Role) -> None:
    """Additional catalog grants cannot narrow organization Administrator authority."""
    grants = Grants("alice", [Grant(Role.ADMINISTRATOR, None), Grant(catalog_role, HELIO)])
    assert grants.role_on(HELIO) is Role.ADMINISTRATOR
    assert grants.role_on(ASTRO) is Role.ADMINISTRATOR
    for minimum in Role:
        grants.require(minimum, HELIO)
        assert grants.readable(minimum) == ReadableCatalogs(True, frozenset())


def test_organization_iteration_precedes_even_an_empty_opaque_catalog_name() -> None:
    """Scope ordering is independent of opaque catalog display names."""
    catalog_grant = Grant(Role.CATALOG_READER, CatalogRef(HELIO.id, ""))
    organization_grant = Grant(Role.ADMINISTRATOR, None)
    assert tuple(Grants("alice", [catalog_grant, organization_grant])) == (
        organization_grant,
        catalog_grant,
    )
