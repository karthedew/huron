"""Informational role claims follow an exact, reversible structural grammar."""

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huron.core.security.broker import ROLE_CLAIM_PREFIX, CatalogRef, ClaimedRole, Grant, Role

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "claim,expected",
    [
        (
            "PRINCIPAL_ROLE:heliophysics.catalog_contributor",
            ClaimedRole(Role.CATALOG_CONTRIBUTOR, "heliophysics"),
        ),
        ("PRINCIPAL_ROLE:helio.catalog_reader", ClaimedRole(Role.CATALOG_READER, "helio")),
        ("PRINCIPAL_ROLE:administrator", ClaimedRole(Role.ADMINISTRATOR, None)),
        (
            "PRINCIPAL_ROLE:solar_wind-2.catalog_owner",
            ClaimedRole(Role.CATALOG_OWNER, "solar_wind-2"),
        ),
    ],
)
def test_accepted_claims_round_trip_exactly(claim: str, expected: ClaimedRole) -> None:
    """The supported organization and catalog claim examples retain their spelling."""
    assert ClaimedRole.parse(claim) == expected
    assert str(expected) == claim


@pytest.mark.parametrize(
    "body,rule",
    [
        ("helio_catalog_contributor", "unknown role code"),
        *(
            (code, "unknown role code")
            for code in (
                "reader",
                "developer",
                "project_admin",
                "organization_admin",
                "platform_owner",
                "helio.reader",
                "helio.developer",
                "helio.project_admin",
                "helio.organization_admin",
                "helio.platform_owner",
            )
        ),
        *(
            (code, "catalog roles require a catalog")
            for code in (
                "catalog_reader",
                "catalog_contributor",
                "catalog_owner",
            )
        ),
        ("heliophysics.administrator", "catalog roles require a catalog"),
        (".catalog_reader", "empty catalog"),
        ("heliophysics.", "empty role code"),
        ("a.b.catalog_reader", "at most one dot"),
        ("ALL", "Polaris pseudo-role"),
        ("heliophysics.Catalog_Contributor", "role codes are lower case"),
        ("", "empty role code"),
        ("catalog_reader ", "unknown role code"),
        (" catalog_reader", "unknown role code"),
        ("system$x.catalog_reader", "Polaris principal-role rule"),
        ("SyStEm$x.catalog_reader", "Polaris principal-role rule"),
        ("a" * 242 + ".catalog_reader", "Polaris principal-role rule"),
    ],
)
def test_invalid_claim_body_names_the_broken_rule(body: str, rule: str) -> None:
    """Malformed claims fail with a reason identifying their broken grammar rule."""
    with pytest.raises(ValueError, match=rule):
        ClaimedRole.parse(ROLE_CLAIM_PREFIX + body)


@pytest.mark.parametrize(
    "claim", ["principal_role:catalog_reader", " PRINCIPAL_ROLE:catalog_reader", "catalog_reader"]
)
def test_prefix_is_case_sensitive_and_never_trimmed(claim: str) -> None:
    """The complete exact prefix is required."""
    with pytest.raises(ValueError, match="prefix"):
        ClaimedRole.parse(claim)


def test_every_role_and_valid_scope_round_trips() -> None:
    """Both round-trip identities hold over all roles and representative scopes."""
    for role in Role:
        for catalog in (None, "heliophysics", "solar_wind-2"):
            if role.catalog_scoped != (catalog is not None):
                with pytest.raises(ValueError, match="catalog roles require a catalog"):
                    ClaimedRole(role, catalog)
                continue
            grant = Grant(role, CatalogRef(UUID(int=1), catalog) if catalog is not None else None)
            claimed = ClaimedRole.of(grant)
            assert claimed == ClaimedRole(role, catalog)
            assert ClaimedRole.parse(str(claimed)) == claimed
            assert str(ClaimedRole.parse(str(claimed))) == str(claimed)


@pytest.mark.parametrize(
    "catalog,rule",
    [
        ("", "empty catalog"),
        ("a.b", "dot"),
        ("system$x", "Polaris principal-role rule"),
        ("a" * 242, "Polaris principal-role rule"),
    ],
)
def test_grant_conversion_and_direct_construction_enforce_grammar(catalog: str, rule: str) -> None:
    """Invalid names cannot enter the claim value through either constructor."""
    with pytest.raises(ValueError, match=rule):
        ClaimedRole.of(Grant(Role.CATALOG_READER, CatalogRef(UUID(int=1), catalog)))
    with pytest.raises(ValueError, match=rule):
        ClaimedRole(Role.CATALOG_READER, catalog)


def test_polaris_length_boundary_and_opaque_catalog_name() -> None:
    """Exactly 256 characters are legal and catalog spelling stays opaque."""
    for catalog in ("a" * 241, " Mixed Case / $ ", "system", "xsystem$"):
        claim = ROLE_CLAIM_PREFIX + catalog + ".catalog_reader"
        assert str(ClaimedRole.parse(claim)) == claim
    with pytest.raises(FrozenInstanceError):
        ClaimedRole(Role.ADMINISTRATOR, None).catalog = "changed"


@given(st.text(alphabet=st.characters(blacklist_characters="."), min_size=1, max_size=100))
def test_opaque_catalog_names_have_lossless_claim_spelling(catalog: str) -> None:
    """Catalog spelling is preserved without importing lake name validation."""
    if catalog.lower().startswith("system$"):
        with pytest.raises(ValueError, match="Polaris principal-role rule"):
            ClaimedRole(Role.CATALOG_READER, catalog)
    else:
        value = ClaimedRole(Role.CATALOG_READER, catalog)
        assert ClaimedRole.parse(str(value)) == value
