"""An API over the in-memory store, with a fake company issuer and group directory."""

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from huron.applications.api.app import create_app
from huron.applications.api.runtime import Runtime, build_runtime
from huron.applications.api.settings import Settings
from huron.core.metastore.store import MemoryStore
from huron.core.security.broker import TokenIssuer
from huron.pkg.clock import FrozenClock
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import AUDIENCE, ISSUER, FakeIssuer
from tests.support.clock import frozen
from tests.support.lake import PLATFORM_GROUP

INSTANCE_ID = uuid.UUID("0192b6a0-0000-7000-8000-000000000001")

USERS: Mapping[str, list[str]] = {
    "alice": [PLATFORM_GROUP],
    "bob": ["helio-org-admins"],
    "carol": ["helio-catalog-admins"],
    "dave": ["helio-contributors"],
    "frank": ["helio-contributors"],
    "erin": ["helio-readers"],
    "mallory": [],
}


def settings(**overrides: object) -> Settings:
    """Settings for an in-memory service."""
    values: dict[str, object] = {
        "store": "memory",
        "instance_id": INSTANCE_ID,
        "issuer": "https://huron.test",
        "company_issuer": ISSUER,
        "company_audience": AUDIENCE,
        "group_directory_url": "https://groups.test",
        "platform_admin_group": PLATFORM_GROUP,
        **overrides,
    }
    return Settings(**values)  # type: ignore[arg-type]


@dataclass
class Service:
    """A running in-process service and the means to call it."""

    runtime: Runtime
    client: httpx.AsyncClient
    issuer: FakeIssuer
    clock: FrozenClock

    async def token(self, user: str) -> str:
        """A Huron token for ``user`` with their configured groups."""
        ring = await self.runtime.ring()
        issuer = TokenIssuer(
            ring,
            self.clock,
            self.runtime.settings.issuer,
            self.runtime.settings.audience,
            self.runtime.settings.token_ttl,
        )
        token, _ = issuer.issue(user, user.title(), USERS[user])
        return token

    async def headers(self, user: str, **extra: str) -> dict[str, str]:
        """Authorization headers for ``user``."""
        return {"Authorization": f"Bearer {await self.token(user)}", **extra}

    async def as_user(self, user: str) -> httpx.AsyncClient:
        """A client that always sends ``user``'s token."""
        client = httpx.AsyncClient(
            transport=self.client._transport,
            base_url="http://huron.test",
            headers=await self.headers(user),
        )
        return client


@asynccontextmanager
async def service(**overrides: object) -> AsyncIterator[Service]:
    """Start an in-process service over a fresh in-memory store."""
    issuer = FakeIssuer()
    clock = frozen()
    runtime = await build_runtime(
        settings(**overrides),
        store=MemoryStore(),
        http=httpx.AsyncClient(transport=issuer.transport()),
        groups=FakeGroups(USERS),
        clock=clock,
    )
    app = create_app(runtime=runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://huron.test") as client:
        yield Service(runtime, client, issuer, clock)
    await runtime.close()
