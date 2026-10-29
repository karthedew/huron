"""A lake over the in-memory store, seeded actors and a seeded catalog."""

from dataclasses import dataclass
from datetime import timedelta

from huron.core.lake.bootstrap import Lake, LakeSettings, bootstrap, build_lake
from huron.core.metastore.store import MemoryStore
from huron.core.security.rbac import Actor, Role
from huron.pkg.clock import FrozenClock
from tests.support.clock import frozen

PLATFORM_GROUP = "huron-platform-admins"
SETTINGS = LakeSettings(platform_admin_group=PLATFORM_GROUP, key_overlap=timedelta(hours=1))


def actor(subject: str, *groups: str) -> Actor:
    """An actor with the given groups."""
    return Actor(subject, subject.title(), frozenset(groups))


PLATFORM_ADMIN = actor("alice", PLATFORM_GROUP)
ORG_ADMIN = actor("bob", "helio-org-admins")
CATALOG_ADMIN = actor("carol", "helio-catalog-admins")
CONTRIBUTOR = actor("dave", "helio-contributors")
OTHER_CONTRIBUTOR = actor("frank", "helio-contributors")
READER = actor("erin", "helio-readers")
STRANGER = actor("mallory", "nobody")


@dataclass
class World:
    """A bootstrapped lake and its store and clock."""

    lake: Lake
    store: MemoryStore
    clock: FrozenClock


async def make_world() -> World:
    """A bootstrapped lake with no organizations."""
    store = MemoryStore()
    clock = frozen()
    await bootstrap(store, clock, SETTINGS)
    return World(build_lake(store, clock, SETTINGS), store, clock)


async def seed(world: World) -> None:
    """Organization ``helio``, catalog ``heliophysics`` with grants, namespace ``solar-wind``."""
    lake = world.lake
    await lake.organizations.create(PLATFORM_ADMIN, "helio", "Heliophysics", "Sun and wind")
    await lake.grants.set_org_admins(PLATFORM_ADMIN, "helio", ["helio-org-admins"])
    await lake.catalogs.create(ORG_ADMIN, "helio", "heliophysics")
    await lake.grants.set_catalog_role(
        ORG_ADMIN, "heliophysics", Role.CATALOG_ADMIN, ["helio-catalog-admins"]
    )
    await lake.grants.set_catalog_role(
        CATALOG_ADMIN, "heliophysics", Role.CONTRIBUTOR, ["helio-contributors"]
    )
    await lake.grants.set_catalog_role(
        CATALOG_ADMIN, "heliophysics", Role.READER, ["helio-readers"]
    )
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "solar-wind", True)


VALID_METADATA = {"title": "Run 7", "description": "Solar wind run seven"}
