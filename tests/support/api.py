"""An API over the in-memory store, with a fake company issuer and group directory."""

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from huron.applications.api.app import create_app
from huron.applications.api.disk import LakeDisk
from huron.applications.api.runtime import Runtime, build_runtime
from huron.applications.api.settings import Settings
from huron.core.metastore.store import MemoryStore
from huron.core.security.broker import TokenIssuer
from huron.core.storage import MARKER_FILE, Marker, render_marker
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


#: The marker of a share or lake root that belongs to the test service.
ROOT_MARKER = render_marker(Marker(1, "http://huron.test", str(INSTANCE_ID)))


def mark_lake(path: Path) -> Path:
    """Make ``path`` a lake of the test service: a directory with the service's root marker."""
    path.mkdir(parents=True, exist_ok=True)
    (path / MARKER_FILE).write_bytes(ROOT_MARKER)
    return path


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
async def service(
    *,
    store: MemoryStore | None = None,
    disk: LakeDisk | None = None,
    clock: FrozenClock | None = None,
    **overrides: object,
) -> AsyncIterator[Service]:
    """Start an in-process service over ``store``, by default a fresh in-memory one.

    ``disk`` replaces the lake's disk that ``lake_path`` would give; ``clock`` must then be the
    clock the disk reads.
    """
    issuer = FakeIssuer()
    clock = clock or frozen()
    runtime = await build_runtime(
        settings(**overrides),
        store=store or MemoryStore(),
        http=httpx.AsyncClient(transport=issuer.transport()),
        groups=FakeGroups(USERS),
        clock=clock,
        disk=disk,
    )
    app = create_app(runtime=runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://huron.test") as client:
        yield Service(runtime, client, issuer, clock)
    await runtime.close()


async def seed_service(api: Service) -> Service:
    """The helio organization, catalog, grants and the solar-wind namespace, through the API."""
    c = api.client
    alice = await api.headers("alice")
    bob = await api.headers("bob")
    carol = await api.headers("carol")
    assert (
        await c.post("/api/v1/organizations", json={"name": "helio"}, headers=alice)
    ).status_code == 201
    await c.put(
        "/api/v1/organizations/helio/grants/org_admin",
        json={"ldap_groups": ["helio-org-admins"]},
        headers=alice,
    )
    assert (
        await c.post(
            "/api/v1/organizations/helio/catalogs", json={"name": "heliophysics"}, headers=bob
        )
    ).status_code == 201
    await c.put(
        "/api/v1/catalogs/heliophysics/grants/catalog_admin",
        json={"ldap_groups": ["helio-catalog-admins"]},
        headers=bob,
    )
    for role, group in (("contributor", "helio-contributors"), ("reader", "helio-readers")):
        await c.put(
            f"/api/v1/catalogs/heliophysics/grants/{role}",
            json={"ldap_groups": [group]},
            headers=carol,
        )
    created = await c.post(
        "/api/v1/catalogs/heliophysics/namespaces",
        json={"name": "solar-wind", "collections_allowed": True},
        headers=carol,
    )
    assert created.status_code == 201, created.text
    return api


#: Valid metadata of a collection in the seeded catalog.
COLLECTION_METADATA = {"title": "Run 7", "description": "Solar wind run seven"}


async def active_collection(api: Service, name: str = "run7") -> dict[str, Any]:
    """Create and activate collection ``name`` in the seeded solar-wind namespace, as dave."""
    created = await api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections",
        json={"name": name, "metadata": COLLECTION_METADATA},
        headers=await api.headers("dave"),
    )
    assert created.status_code == 201, created.text
    activated = await api.client.post(
        f"/api/v1/collections/{created.json()['id']}/activate",
        headers=await api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert activated.status_code == 200, activated.text
    collection: dict[str, Any] = activated.json()
    return collection
