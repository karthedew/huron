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
        ("PRINCIPAL_ROLE:heliophysics.developer", ClaimedRole(Role.DEVELOPER, "heliophysics")),
        ("PRINCIPAL_ROLE:reader", ClaimedRole(Role.READER, None)),
        ("PRINCIPAL_ROLE:platform_owner", ClaimedRole(Role.PLATFORM_OWNER, None)),
        (
            "PRINCIPAL_ROLE:solar_wind-2.project_admin",
            ClaimedRole(Role.PROJECT_ADMIN, "solar_wind-2"),
        ),
    ],
)
def test_accepted_claims_round_trip_exactly(claim: str, expected: ClaimedRole) -> None:
    """The supported global and catalog claim examples retain their spelling."""
    assert ClaimedRole.parse(claim) == expected
    assert str(expected) == claim


@pytest.mark.parametrize(
    "body,rule",
    [
        ("helio_developer", "unknown role code"),
        ("heliophysics.platform_owner", "global-only role"),
        (".reader", "empty catalog"),
        ("heliophysics.", "empty role code"),
        ("a.b.reader", "at most one dot"),
        ("ALL", "Polaris pseudo-role"),
        ("heliophysics.Developer", "role codes are lower case"),
        ("", "empty role code"),
        ("reader ", "unknown role code"),
        (" reader", "unknown role code"),
        ("system$x.reader", "Polaris principal-role rule"),
        ("SyStEm$x.reader", "Polaris principal-role rule"),
        ("a" * 250 + ".reader", "Polaris principal-role rule"),
    ],
)
def test_invalid_claim_body_names_the_broken_rule(body: str, rule: str) -> None:
    """Malformed claims fail with a reason identifying their broken grammar rule."""
    with pytest.raises(ValueError, match=rule):
        ClaimedRole.parse(ROLE_CLAIM_PREFIX + body)


@pytest.mark.parametrize("claim", ["principal_role:reader", " PRINCIPAL_ROLE:reader", "reader"])
def test_prefix_is_case_sensitive_and_never_trimmed(claim: str) -> None:
    """The complete exact prefix is required."""
    with pytest.raises(ValueError, match="prefix"):
        ClaimedRole.parse(claim)


def test_every_role_and_valid_scope_round_trips() -> None:
    """Both round-trip identities hold over all roles and representative scopes."""
    for role in Role:
        for catalog in (None, "heliophysics", "solar_wind-2"):
            grant = Grant(role, CatalogRef(UUID(int=1), catalog) if catalog is not None else None)
            if catalog is not None and not role.catalog_scoped:
                with pytest.raises(ValueError, match="global-only role"):
                    ClaimedRole.of(grant)
                continue
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
        ("a" * 250, "Polaris principal-role rule"),
    ],
)
def test_grant_conversion_and_direct_construction_enforce_grammar(catalog: str, rule: str) -> None:
    """Invalid names cannot enter the claim value through either constructor."""
    with pytest.raises(ValueError, match=rule):
        ClaimedRole.of(Grant(Role.READER, CatalogRef(UUID(int=1), catalog)))
    with pytest.raises(ValueError, match=rule):
        ClaimedRole(Role.READER, catalog)


def test_polaris_length_boundary_and_opaque_catalog_name() -> None:
    """Exactly 256 characters are legal and catalog spelling stays opaque."""
    for catalog in ("a" * 249, " Mixed Case / $ ", "system", "xsystem$"):
        claim = ROLE_CLAIM_PREFIX + catalog + ".reader"
        assert str(ClaimedRole.parse(claim)) == claim
    with pytest.raises(FrozenInstanceError):
        ClaimedRole(Role.READER, None).catalog = "changed"


@given(st.text(alphabet=st.characters(blacklist_characters="."), min_size=1, max_size=100))
def test_opaque_catalog_names_have_lossless_claim_spelling(catalog: str) -> None:
    """Catalog spelling is preserved without importing lake name validation."""
    if catalog.lower().startswith("system$"):
        with pytest.raises(ValueError, match="Polaris principal-role rule"):
            ClaimedRole(Role.READER, catalog)
    else:
        value = ClaimedRole(Role.READER, catalog)
        assert ClaimedRole.parse(str(value)) == value
