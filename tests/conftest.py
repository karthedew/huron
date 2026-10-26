"""Shared clocks and identity-provider boundaries for every test tier."""

import httpx
import pytest

from tests.fakes.ldap_groups import FakeGroupDirectory, Identities
from tests.fakes.oidc_issuer import FakeCompanyIdp
from tests.lake_tokens import TEST_EPOCH
from tests.unit.support import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    """Supply one controllable clock for the app and its identity provider."""
    return FakeClock(TEST_EPOCH)


@pytest.fixture
def identities() -> Identities:
    """Load an immutable directory of the shared development people."""
    return Identities.load()


@pytest.fixture
def fake_groups(identities: Identities) -> FakeGroupDirectory:
    """Supply an isolated directory service with Python fault controls."""
    return FakeGroupDirectory(identities)


@pytest.fixture
def fake_groups_transport(fake_groups: FakeGroupDirectory) -> httpx.ASGITransport:
    """Deliver group lookups in-process without resolving a remote host."""
    return httpx.ASGITransport(app=fake_groups.app)


@pytest.fixture
def fake_issuer(identities: Identities, clock: FakeClock) -> FakeCompanyIdp:
    """Supply a company issuer sharing the application's controllable clock."""
    return FakeCompanyIdp(identities, clock)


@pytest.fixture
def fake_issuer_transport(fake_issuer: FakeCompanyIdp) -> httpx.ASGITransport:
    """Deliver issuer requests without network access or wall-clock waits."""
    return httpx.ASGITransport(app=fake_issuer.app)
