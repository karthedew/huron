"""The whole service over PostgreSQL, walked through HTTP as every role."""

import httpx
import pytest

from huron.applications.api.app import create_app
from huron.applications.api.runtime import build_runtime
from huron.core.metastore.postgres import PostgresStore
from huron.core.security.broker import TokenIssuer
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import FakeIssuer
from tests.support.api import USERS, settings
from tests.support.clock import START, frozen
from tests.support.postgres import truncate

pytestmark = pytest.mark.integration
SHA = "d" * 64


async def test_section_one_end_to_end(database_url: str) -> None:
    await truncate(database_url)
    store = PostgresStore(database_url)
    await store.connect()
    issuer = FakeIssuer()
    clock = frozen()
    runtime = await build_runtime(
        settings(store="postgres", database_url=database_url),
        store=store,
        http=httpx.AsyncClient(transport=issuer.transport()),
        groups=FakeGroups(USERS),
        clock=clock,
    )
    app = create_app(runtime=runtime)
    ring = await runtime.ring()
    tokens = TokenIssuer(ring, clock, "https://huron.test", "huron", runtime.settings.token_ttl)

    def as_(user: str, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.issue(user, user, USERS[user])[0]}", **extra}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as c:
        exchanged = await c.post(
            "/auth/exchange", json={"company_token": issuer.sign("dave", now=START.timestamp())}
        )
        assert exchanged.json()["groups"] == ["helio-contributors"]
        assert (
            await c.post("/organizations", json={"name": "helio"}, headers=as_("alice"))
        ).status_code == 201
        await c.put(
            "/organizations/helio/grants/org_admin",
            json={"ldap_groups": ["helio-org-admins"]},
            headers=as_("alice"),
        )
        assert (
            await c.post(
                "/organizations/helio/catalogs", json={"name": "heliophysics"}, headers=as_("bob")
            )
        ).status_code == 201
        await c.put(
            "/catalogs/heliophysics/grants/catalog_admin",
            json={"ldap_groups": ["helio-catalog-admins"]},
            headers=as_("bob"),
        )
        for role, group in (("contributor", "helio-contributors"), ("reader", "helio-readers")):
            await c.put(
                f"/catalogs/heliophysics/grants/{role}",
                json={"ldap_groups": [group]},
                headers=as_("carol"),
            )
        await c.post(
            "/catalogs/heliophysics/namespaces",
            json={"name": "solar-wind", "collections_allowed": True},
            headers=as_("carol"),
        )
        meta = {"title": "Run 7", "description": "Solar wind", "labels": {"site": "a"}}
        draft = (
            await c.post(
                "/catalogs/heliophysics/namespaces/solar-wind/collections",
                json={"name": "run7", "metadata": meta},
                headers=as_("dave"),
            )
        ).json()
        cid = draft["id"]
        activated = await c.post(
            f"/collections/{cid}/activate", headers=as_("dave", **{"If-Match": '"1"'})
        )
        assert activated.json()["state"] == "active"
        body = {
            "base_version": 2,
            "adds": [{"rel_path": "a.txt", "size": 1, "sha256": SHA}],
            "removes": [],
            "host": "ws1",
        }
        assert (await c.post(f"/collections/{cid}/commits", json=body, headers=as_("dave"))).json()[
            "version"
        ] == 3
        stale = await c.post(f"/collections/{cid}/commits", json=body, headers=as_("dave"))
        assert stale.json()["code"] == "BASE_VERSION_CONFLICT"
        found = await c.get(
            "/catalogs/heliophysics/search?q=wind&label=site=a", headers=as_("erin")
        )
        assert [x["name"] for x in found.json()["items"]] == ["run7"]
        log = await c.get(f"/collections/{cid}/log", headers=as_("erin"))
        assert [e["action"] for e in log.json()["items"]][:2] == [
            "collection.commit",
            "collection.activate",
        ]
        refused = await c.post(
            f"/collections/{cid}/commits", json={**body, "base_version": 3}, headers=as_("erin")
        )
        assert refused.status_code == 403
    await runtime.close()
