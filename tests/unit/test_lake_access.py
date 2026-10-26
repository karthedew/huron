"""Lake authentication resolves current authority only after verifying signed identity."""

from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from huron.core.foundation.errors import AuthError, Forbidden
from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.security.broker import (
    VERIFY_LEEWAY,
    Actor,
    CatalogRef,
    Grant,
    Grants,
    HuronTokenVerifier,
    LakeAuthentication,
    Role,
)
from tests.lake_store_contract import MemorySeed
from tests.lake_tokens import TEST_EPOCH, TEST_ISSUER, TEST_KID, mint, refreshed_test_keys
from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit
CATALOG = CatalogRef(UUID(int=1), "heliophysics")
OTHER = CatalogRef(UUID(int=2), "genomics")


class ObservedMappings:
    """Observe persistence reads and optionally fail the storage boundary."""

    def __init__(self, store: InMemoryLakeStore) -> None:
        self.store = store
        self.calls: list[frozenset[str]] = []
        self.failure: Exception | None = None

    async def roles_for_groups(self, groups: frozenset[str]) -> tuple[Grant, ...]:
        """Record every read and delegate to committed rows unless storage fails."""
        self.calls.append(groups)
        if self.failure is not None:
            raise self.failure
        return await self.store.roles_for_groups(groups)


async def test_current_catalog_authority_and_immutable_identity() -> None:
    """Verified identity keeps current catalog grants isolated and immutable."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    store = InMemoryLakeStore()
    seed = MemorySeed(store)
    await seed.ldap_group("scientists", 101)
    await seed.ldap_group("owners", 102)
    await seed.role_mapping("scientists", CATALOG, Role.CATALOG_READER)
    await seed.role_mapping("owners", CATALOG, Role.CATALOG_OWNER)
    await seed.role_mapping("scientists", OTHER, Role.CATALOG_CONTRIBUTOR)
    groups = frozenset({"scientists", "owners", "unknown"})
    token = mint(keys, clock, subject="alice", groups=groups)
    mappings = ObservedMappings(store)
    authentication = LakeAuthentication(
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
    )
    actor = await authentication.authenticate(token)
    assert isinstance(actor, Actor)
    assert actor.subject == "alice"
    assert actor.groups == groups
    assert actor.grants.role_on(CATALOG) == Role.CATALOG_OWNER
    assert actor.grants.role_on(OTHER) == Role.CATALOG_CONTRIBUTOR
    assert actor.grants.role_on(CatalogRef(UUID(int=3), "unrelated")) is None
    assert actor.grants.readable().ids == {CATALOG.id, OTHER.id}
    assert not actor.grants.readable().every
    with pytest.raises(Forbidden) as caught:
        actor.grants.require(Role.ADMINISTRATOR)
    assert caught.value.context["subject"] == "alice"
    assert mappings.calls == [groups]
    for field in ("subject", "groups", "grants"):
        with pytest.raises(FrozenInstanceError):
            setattr(actor, field, getattr(actor, field))
    assert isinstance(actor.groups, frozenset)


@pytest.mark.parametrize("role", [Role.ADMINISTRATOR, Role.CATALOG_OWNER])
async def test_same_token_loses_authority_when_mapping_is_removed(role: Role) -> None:
    """Removing a mapping immediately revokes its authority on the next authentication."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    store = InMemoryLakeStore()
    seed = MemorySeed(store)
    catalog = None if role == Role.ADMINISTRATOR else CATALOG
    await seed.ldap_group("scientists", 101)
    await seed.role_mapping("scientists", catalog, role)
    groups = frozenset({"scientists"})
    token = mint(keys, clock, groups=groups, grants=Grants("karl", [Grant(role, catalog)]))
    mappings = ObservedMappings(store)
    authentication = LakeAuthentication(
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
    )
    first = await authentication.authenticate(token)
    assert first.grants.role_on(CATALOG) == role
    await seed.remove_role_mapping("scientists", catalog)
    second = await authentication.authenticate(token)
    assert not second.grants
    assert first.grants.role_on(CATALOG) == role
    assert mappings.calls == [groups, groups]


async def test_same_token_observes_catalog_role_downgrade() -> None:
    """Replacing an Owner mapping with Reader reduces only that catalog's authority."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    store = InMemoryLakeStore()
    seed = MemorySeed(store)
    await seed.ldap_group("scientists", 101)
    await seed.role_mapping("scientists", CATALOG, Role.CATALOG_OWNER)
    await seed.role_mapping("scientists", OTHER, Role.CATALOG_CONTRIBUTOR)
    groups = frozenset({"scientists"})
    token = mint(
        keys, clock, groups=groups, grants=Grants("karl", [Grant(Role.CATALOG_OWNER, CATALOG)])
    )
    mappings = ObservedMappings(store)
    authentication = LakeAuthentication(
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
    )
    assert (await authentication.authenticate(token)).grants.role_on(CATALOG) == Role.CATALOG_OWNER
    await seed.role_mapping("scientists", CATALOG, Role.CATALOG_READER)
    actor = await authentication.authenticate(token)
    assert actor.grants.role_on(CATALOG) == Role.CATALOG_READER
    assert actor.grants.role_on(OTHER) == Role.CATALOG_CONTRIBUTOR
    with pytest.raises(Forbidden):
        actor.grants.require(Role.CATALOG_CONTRIBUTOR, CATALOG)
    assert mappings.calls == [groups, groups]


@pytest.mark.parametrize("groups", [frozenset(), frozenset({"unknown"}), frozenset({"unmapped"})])
async def test_informational_administrator_never_replaces_current_mappings(
    groups: frozenset[str],
) -> None:
    """Empty, unknown and unmapped groups grant nothing despite a signed Administrator claim."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    store = InMemoryLakeStore()
    await MemorySeed(store).ldap_group("unmapped", 101)
    token = mint(
        keys, clock, groups=groups, grants=Grants("karl", [Grant(Role.ADMINISTRATOR, None)])
    )
    mappings = ObservedMappings(store)
    actor = await LakeAuthentication(
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
    ).authenticate(token)
    assert not actor.grants
    assert actor.groups == groups
    assert mappings.calls == [groups]


@pytest.mark.parametrize("invalid", ["malformed", "expired", "wrong_key"])
async def test_invalid_tokens_never_read_mappings(invalid: str) -> None:
    """Token shape, expiry and signature failures cost no persistence read."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    token = mint(keys, clock)
    if invalid == "malformed":
        token = "not-a-token"
    elif invalid == "expired":
        clock.advance(timedelta(hours=1) + VERIFY_LEEWAY)
    else:
        payload = jwt.decode(token, options={"verify_signature": False})
        wrong_key = ec.derive_private_key(123, ec.SECP256R1())
        token = jwt.encode(payload, wrong_key, algorithm="ES256", headers={"kid": TEST_KID})
    mappings = ObservedMappings(InMemoryLakeStore())
    with pytest.raises(AuthError):
        await LakeAuthentication(
            HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
        ).authenticate(token)
    assert mappings.calls == []


async def test_mapping_failure_propagates_and_recovery_reads_again() -> None:
    """An outage propagates unchanged; recovery reads current rows without cached failure grants."""
    clock = FakeClock(TEST_EPOCH)
    keys = await refreshed_test_keys(clock)
    store = InMemoryLakeStore()
    seed = MemorySeed(store)
    await seed.ldap_group("scientists", 101)
    await seed.role_mapping("scientists", CATALOG, Role.CATALOG_READER)
    groups = frozenset({"scientists"})
    token = mint(keys, clock, groups=groups)
    mappings = ObservedMappings(store)
    authentication = LakeAuthentication(
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock), mappings
    )
    assert (await authentication.authenticate(token)).grants
    failure = ConnectionError("mapping store unavailable")
    mappings.failure = failure
    with pytest.raises(ConnectionError) as caught:
        await authentication.authenticate(token)
    assert caught.value is failure
    mappings.failure = None
    await seed.role_mapping("scientists", CATALOG, Role.CATALOG_OWNER)
    assert (await authentication.authenticate(token)).grants.role_on(CATALOG) == Role.CATALOG_OWNER
    assert mappings.calls == [groups, groups, groups]
