"""The schema registry, catalogs and schema assignment."""

import uuid

import pytest

from huron.core.lake.catalogs.errors import CatalogNotEmpty
from huron.core.lake.errors import NameTaken
from huron.core.lake.schemas.errors import SchemaScope
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.pkg.errors import Forbidden, NotFound
from huron.pkg.paging import InvalidCursor, encode_cursor
from huron.schema.composition import SchemaIncompatible
from huron.schema.validator import SchemaInvalid
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    PLATFORM_ADMIN,
    READER,
    STRANGER,
    World,
)

HELIO = {
    "type": "object",
    "properties": {"mission": {"type": "string"}},
    "required": ["mission"],
}


async def base_id(world: World) -> uuid.UUID:
    page = await world.lake.schemas.list(PLATFORM_ADMIN, None, None, None)
    return next(e.id for e in page.items if e.name == BASE_SCHEMA_NAME)


async def test_bootstrap_installs_the_base_schema(world: World) -> None:
    entry = await world.lake.schemas.get(READER, await base_id(world))
    assert entry.version == 1 and entry.organization_id is None
    assert entry.as_dict()["scope"] == "platform"
    resolved = await world.lake.schemas.resolved(STRANGER, entry.id)
    assert resolved["required"] == ["title", "description"]


async def test_organization_schemas_extend_the_base_and_version(seeded: World) -> None:
    lake = seeded.lake
    base = await base_id(seeded)
    first = await lake.schemas.publish(ORG_ADMIN, "helio", "helio", base, HELIO)
    second = await lake.schemas.publish(ORG_ADMIN, "helio", "helio", base, HELIO)
    assert (first.version, second.version) == (1, 2)
    resolved = await lake.schemas.resolved(READER, second.id)
    assert resolved["required"] == ["title", "description", "mission"]
    listed = await lake.schemas.list(READER, "helio", None, 1)
    assert [e.version for e in listed.items] == [2]
    rest = await lake.schemas.list(READER, "helio", listed.next_cursor, 1)
    assert [e.version for e in rest.items] == [1]
    with pytest.raises(InvalidCursor):
        await lake.schemas.list(READER, "helio", encode_cursor(["x"]), 1)
    with pytest.raises(NotFound):
        await lake.schemas.get(STRANGER, first.id)


async def test_publishing_refuses_bad_documents_and_scopes(seeded: World) -> None:
    lake = seeded.lake
    base = await base_id(seeded)
    with pytest.raises(SchemaInvalid):
        await lake.schemas.publish(ORG_ADMIN, "helio", "x", base, {"type": "array"})
    with pytest.raises(SchemaIncompatible):
        await lake.schemas.publish(ORG_ADMIN, "helio", "x", None, HELIO)
    bad = {"type": "object", "properties": {"title": {"type": "integer"}}}
    with pytest.raises(SchemaIncompatible):
        await lake.schemas.publish(ORG_ADMIN, "helio", "x", base, bad)
    with pytest.raises(NotFound):
        await lake.schemas.publish(ORG_ADMIN, "helio", "x", uuid.uuid4(), HELIO)
    with pytest.raises(Forbidden):
        await lake.schemas.publish(CATALOG_ADMIN, "helio", "x", base, HELIO)
    with pytest.raises(Forbidden):
        await lake.schemas.publish(ORG_ADMIN, None, "x", base, HELIO)
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    geo = await lake.schemas.publish(PLATFORM_ADMIN, "geo", "geo", base, HELIO)
    with pytest.raises(SchemaScope):
        await lake.schemas.publish(PLATFORM_ADMIN, "helio", "x", geo.id, HELIO)
    platform = await lake.schemas.publish(PLATFORM_ADMIN, None, BASE_SCHEMA_NAME, None, HELIO)
    assert platform.version == 2


async def test_catalogs_default_to_the_latest_base_schema(seeded: World) -> None:
    view = await seeded.lake.catalogs.get(READER, "heliophysics")
    assert view.schema.name == BASE_SCHEMA_NAME
    assert view.organization == "helio"
    assert view.as_dict()["namespace_count"] == 1
    with pytest.raises(NotFound):
        await seeded.lake.catalogs.get(STRANGER, "heliophysics")


async def test_catalog_names_are_unique_across_organizations(seeded: World) -> None:
    lake = seeded.lake
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    with pytest.raises(NameTaken):
        await lake.catalogs.create(PLATFORM_ADMIN, "geo", "heliophysics")
    with pytest.raises(Forbidden):
        await lake.catalogs.create(CATALOG_ADMIN, "helio", "another")


async def test_catalog_listing_respects_visibility(seeded: World) -> None:
    lake = seeded.lake
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    await lake.catalogs.create(PLATFORM_ADMIN, "geo", "geophysics")
    await lake.catalogs.create(ORG_ADMIN, "helio", "aurora")
    names = lambda page: [v.catalog.name for v in page.items]  # noqa: E731
    assert names(await lake.catalogs.list(PLATFORM_ADMIN)) == [
        "aurora",
        "geophysics",
        "heliophysics",
    ]
    assert names(await lake.catalogs.list(ORG_ADMIN)) == ["aurora", "heliophysics"]
    assert names(await lake.catalogs.list(READER)) == ["heliophysics"]
    assert names(await lake.catalogs.list(PLATFORM_ADMIN, "geo")) == ["geophysics"]
    assert names(await lake.catalogs.list(READER, "helio")) == ["heliophysics"]
    first = await lake.catalogs.list(PLATFORM_ADMIN, limit=2)
    assert names(await lake.catalogs.list(PLATFORM_ADMIN, cursor=first.next_cursor)) == [
        "heliophysics"
    ]


async def test_catalogs_with_namespaces_cannot_be_deleted(seeded: World) -> None:
    lake = seeded.lake
    with pytest.raises(CatalogNotEmpty):
        await lake.catalogs.delete(ORG_ADMIN, "heliophysics")
    await lake.catalogs.create(ORG_ADMIN, "helio", "empty")
    with pytest.raises(Forbidden):
        await lake.catalogs.delete(CATALOG_ADMIN, "heliophysics")
    await lake.catalogs.delete(ORG_ADMIN, "empty")
    with pytest.raises(NotFound):
        await lake.catalogs.get(ORG_ADMIN, "empty")


async def test_schema_assignment_checks_scope(seeded: World) -> None:
    lake = seeded.lake
    base = await base_id(seeded)
    await lake.organizations.create(PLATFORM_ADMIN, "geo")
    geo = await lake.schemas.publish(PLATFORM_ADMIN, "geo", "geo", base, HELIO)
    with pytest.raises(SchemaScope):
        await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", geo.id)
    with pytest.raises(NotFound):
        await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", uuid.uuid4())
    with pytest.raises(Forbidden):
        await lake.catalogs.assign_schema(CONTRIBUTOR, "heliophysics", base)
    helio = await lake.schemas.publish(ORG_ADMIN, "helio", "helio", base, HELIO)
    view, result = await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", helio.id)
    assert view.schema.id == helio.id and view.catalog.version == 2
    assert result.as_dict() == {"active": 0, "incomplete": 0, "changed": 0}
    resolved = await lake.catalogs.resolved_schema(READER, "heliophysics")
    assert "mission" in resolved["required"]
    created = await lake.catalogs.create(ORG_ADMIN, "helio", "with-schema", schema_id=helio.id)
    assert created.schema.id == helio.id
