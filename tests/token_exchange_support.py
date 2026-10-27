"""Real broker composition over controllable HTTP and persistence boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx

from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.security.broker import (
    CompanyTokenVerifier,
    HttpGroupDirectory,
    HuronTokenIssuer,
    TokenExchange,
    Grant,
)
from tests.fakes.ldap_groups import FakeGroupDirectory, Identities
from tests.fakes.oidc_issuer import FakeCompanyIdp
from tests.lake_tokens import TEST_ISSUER, refreshed_test_keys
from tests.unit.support import FakeClock


class ObservedRoleMappings:
    """Observe reads and inject persistence failures while keeping the real store."""

    def __init__(self, store: InMemoryLakeStore) -> None:
        self.store = store
        self.calls: list[frozenset[str]] = []
        self.failure: Exception | None = None

    async def roles_for_groups(self, groups: frozenset[str]) -> tuple[Grant, ...]:
        """Read the real rows unless the persistence boundary is unavailable."""
        self.calls.append(groups)
        if self.failure is not None:
            raise self.failure
        return await self.store.roles_for_groups(groups)


@dataclass
class ExchangeContext:
    """Expose the composed workflow and its external test boundaries."""

    exchange: TokenExchange
    company: FakeCompanyIdp
    directory: FakeGroupDirectory
    store: InMemoryLakeStore
    mappings: ObservedRoleMappings


@asynccontextmanager
async def exchange_context(
    identities: Identities, clock: FakeClock, *, subject_claim: str = "preferred_username"
) -> AsyncIterator[ExchangeContext]:
    """Compose production broker collaborators and close their HTTP clients afterward."""
    company = FakeCompanyIdp(identities, clock)
    directory = FakeGroupDirectory(identities)
    store = InMemoryLakeStore()
    mappings = ObservedRoleMappings(store)
    keys = await refreshed_test_keys(clock)
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=company.app)) as company_http,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=directory.app)) as directory_http,
    ):
        yield ExchangeContext(
            TokenExchange(
                CompanyTokenVerifier(
                    company_http,
                    issuer=company.issuer,
                    audiences=frozenset({company.client_id}),
                    clock=clock,
                ),
                HttpGroupDirectory(
                    directory_http, url_template="https://groups.test/users/{username}/groups"
                ),
                mappings,
                HuronTokenIssuer(
                    keys,
                    issuer=TEST_ISSUER,
                    audience=("huron-api",),
                    ttl=timedelta(minutes=10),
                    clock=clock,
                ),
                subject_claim=subject_claim,
            ),
            company,
            directory,
            store,
            mappings,
        )
