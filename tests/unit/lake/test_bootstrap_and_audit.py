"""Bootstrap, signing keys and the audit log."""

from datetime import timedelta

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.bootstrap import bootstrap
from huron.core.lake.collections.models import Update
from huron.pkg.errors import Forbidden
from tests.support.lake import (
    CONTRIBUTOR,
    PLATFORM_ADMIN,
    READER,
    SETTINGS,
    STRANGER,
    VALID_METADATA,
    World,
)


async def test_bootstrap_is_idempotent(world: World) -> None:
    again = await bootstrap(world.store, world.clock, SETTINGS)
    assert (again.base_schema, again.platform_grant, again.signing_key) == (False, False, False)
    assert len(world.store.state.keys) == 1
    assert world.store.state.audit == []


async def test_rotation_retires_the_previous_key(world: World) -> None:
    before = await world.lake.keys.ring()
    with pytest.raises(Forbidden):
        await world.lake.keys.rotate(READER)
    world.clock.advance(timedelta(seconds=1))
    key = await world.lake.keys.rotate(PLATFORM_ADMIN)
    ring = await world.lake.keys.ring()
    assert ring.current.kid == key.kid != before.current.kid
    listed = await world.lake.keys.list(PLATFORM_ADMIN)
    assert listed[0].kid == key.kid
    assert listed[1].retired_at is not None
    world.clock.advance(timedelta(hours=2))
    assert [k["kid"] for k in (await world.lake.keys.ring()).jwks()["keys"]] == [key.kid]
    assert world.store.state.audit[-1].action is Action.SIGNING_KEY_ROTATE


async def test_audit_log_pages_newest_first(seeded: World) -> None:
    lake = seeded.lake
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "run7")
    await lake.collections.update(
        CONTRIBUTOR, draft.collection.id, 1, Update(metadata_patch=VALID_METADATA)
    )
    await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 2)
    page = await lake.audit.for_collection(READER, draft.collection.id, limit=2)
    assert [e.action for e in page.items] == [
        Action.COLLECTION_ACTIVATE,
        Action.COLLECTION_UPDATE_METADATA,
    ]
    rest = await lake.audit.for_collection(READER, draft.collection.id, cursor=page.next_cursor)
    assert [e.action for e in rest.items] == [Action.COLLECTION_CREATE]
    catalog_log = await lake.audit.for_catalog(READER, "heliophysics", limit=500)
    assert catalog_log.items[0].action is Action.COLLECTION_ACTIVATE
    assert catalog_log.items[0].as_dict()["actor"] == "dave"
    with pytest.raises(Exception):  # noqa: B017
        await lake.audit.for_catalog(STRANGER, "heliophysics")


async def test_catalog_log_hides_drafts_and_deleted_collections_from_readers(
    seeded: World,
) -> None:
    lake = seeded.lake
    secret = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "secret")
    gone = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "gone")
    await lake.collections.delete(CONTRIBUTOR, gone.collection.id, 1)
    shown = await lake.audit.for_catalog(READER, "heliophysics", limit=500)
    hidden = {secret.collection.id, gone.collection.id}
    assert not [e for e in shown.items if e.object_id in hidden]
    assert any(e.action is Action.NAMESPACE_CREATE for e in shown.items)
    full = await lake.audit.for_catalog(CONTRIBUTOR, "heliophysics", limit=500)
    assert {e.object_id for e in full.items} >= hidden


async def test_catalog_log_pages_by_raw_entries_when_some_are_hidden(seeded: World) -> None:
    lake = seeded.lake
    await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "secret")
    first = await lake.audit.for_catalog(READER, "heliophysics", limit=1)
    assert first.items == () and first.next_cursor is not None
    rest = await lake.audit.for_catalog(READER, "heliophysics", cursor=first.next_cursor)
    assert rest.items and rest.next_cursor is None
