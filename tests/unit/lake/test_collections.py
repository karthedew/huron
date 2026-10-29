"""The collection lifecycle, metadata, overrides, search and deletion."""

import uuid

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.collections.errors import (
    CollectionNotEmpty,
    CollectionsNotAllowed,
    MetadataInvalid,
)
from huron.core.lake.collections.metadata import check_metadata, merge_patch, render_sidecar
from huron.core.lake.collections.models import Search, State, Update
from huron.core.lake.errors import NameTaken, VersionConflict
from huron.core.lake.files.models import CommitRequest, FileAdd
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.pkg.errors import Conflict, Forbidden, NotFound
from huron.schema.composition import SchemaIncompatible
from huron.schema.naming import NamingError
from huron.schema.validator import SchemaInvalid
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    OTHER_CONTRIBUTOR,
    PLATFORM_ADMIN,
    READER,
    STRANGER,
    VALID_METADATA,
    World,
)

SHA = "0" * 64


async def active(world: World, name: str = "run7", metadata: dict | None = None):  # type: ignore[no-untyped-def,type-arg]
    lake = world.lake
    draft = await lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", name, metadata or dict(VALID_METADATA)
    )
    return await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)


async def test_drafts_accept_invalid_metadata_and_report_problems(seeded: World) -> None:
    lake = seeded.lake
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "run7")
    assert draft.collection.state is State.DRAFT
    assert draft.disk_path is None
    rules = {p["path"] for p in draft.problems}
    assert rules == {"/"}
    with pytest.raises(MetadataInvalid):
        await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)
    patched = await lake.collections.update(
        CONTRIBUTOR, draft.collection.id, 1, Update(metadata_patch=VALID_METADATA)
    )
    assert patched.problems == [] and patched.collection.version == 2
    activated = await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 2)
    assert activated.collection.state is State.ACTIVE
    assert activated.disk_path == "helio/heliophysics/solar-wind/run7"
    assert activated.as_dict()["path"] == "helio/heliophysics/solar-wind/run7"
    with pytest.raises(Conflict):
        await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 3)


async def test_creation_needs_a_namespace_that_allows_collections(seeded: World) -> None:
    lake = seeded.lake
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "closed")
    with pytest.raises(CollectionsNotAllowed):
        await lake.collections.create(CONTRIBUTOR, "heliophysics", "closed", "x")
    with pytest.raises(Forbidden):
        await lake.collections.create(READER, "heliophysics", "solar-wind", "x")
    with pytest.raises(NamingError):
        await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "X")
    with pytest.raises(MetadataInvalid):
        await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "x", [])  # type: ignore[arg-type]
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "taken")
    with pytest.raises(NameTaken):
        await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "taken")


async def test_drafts_are_hidden_from_readers(seeded: World) -> None:
    lake = seeded.lake
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    await active(seeded, "a")
    with pytest.raises(NotFound):
        await lake.collections.get(READER, draft.collection.id)
    listed = await lake.collections.list(READER, "heliophysics", "solar-wind")
    assert [v.collection.name for v in listed.items] == ["a"]
    listed = await lake.collections.list(CONTRIBUTOR, "heliophysics", "solar-wind", limit=1)
    assert [v.collection.name for v in listed.items] == ["a"]
    assert listed.next_cursor is not None
    by_identifier = await lake.collections.get(READER, identifier="heliophysics.solar-wind.a")
    assert by_identifier.collection.name == "a"
    with pytest.raises(NotFound):
        await lake.collections.get(STRANGER, identifier="heliophysics.solar-wind.a")
    with pytest.raises(NotFound):
        await lake.collections.get(READER, uuid.uuid4())


async def test_settled_collections_refuse_invalid_metadata(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    with pytest.raises(MetadataInvalid) as raised:
        await lake.collections.update(
            CONTRIBUTOR, view.collection.id, 2, Update(metadata_patch={"title": None})
        )
    assert raised.value.context["problems"][0]["rule"] == "required"
    with pytest.raises(VersionConflict) as conflict:
        await lake.collections.update(CONTRIBUTOR, view.collection.id, 1, Update())
    assert conflict.value.context == {"current_version": 2}
    with pytest.raises(Forbidden):
        await lake.collections.update(READER, view.collection.id, 2, Update())


async def test_override_and_metadata_validate_together(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    override = {
        "type": "object",
        "properties": {"run": {"type": "integer", "minimum": 1}},
        "required": ["run"],
    }
    with pytest.raises(MetadataInvalid):
        await lake.collections.update(
            CONTRIBUTOR, view.collection.id, 2, Update(schema_override=override)
        )
    updated = await lake.collections.update(
        CONTRIBUTOR,
        view.collection.id,
        2,
        Update(metadata_patch={"run": 7}, schema_override=override),
    )
    assert updated.collection.schema_override == override
    schema = await lake.collections.resolved_schema(READER, view.collection.id)
    assert schema["required"] == ["title", "description", "run"]
    with pytest.raises(SchemaInvalid):
        await lake.collections.update(
            CONTRIBUTOR, view.collection.id, 3, Update(schema_override={"type": "array"})
        )
    with pytest.raises(SchemaIncompatible):
        await lake.collections.update(
            CONTRIBUTOR,
            view.collection.id,
            3,
            Update(
                schema_override={"type": "object", "properties": {"title": {"type": "integer"}}}
            ),
        )
    cleared = await lake.collections.update(
        CONTRIBUTOR, view.collection.id, 3, Update(schema_override=None)
    )
    assert cleared.collection.schema_override is None
    actions = [e.action for e in seeded.store.state.audit if e.object_id == view.collection.id]
    assert actions.count(Action.COLLECTION_SET_SCHEMA_OVERRIDE) == 2
    assert Action.COLLECTION_UPDATE_METADATA in actions


async def test_assigning_a_stricter_schema_marks_collections_incomplete(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    untouched = await active(seeded, "other", {**VALID_METADATA, "mission": "parker"})
    base_page = await lake.schemas.list(READER, None, None, None)
    base = base_page.items[0].id
    strict = await lake.schemas.publish(
        CATALOG_ADMIN.__class__("bob", "Bob", frozenset({"helio-org-admins"})),
        "helio",
        "strict",
        base,
        {"type": "object", "properties": {"mission": {"type": "string"}}, "required": ["mission"]},
    )
    _, result = await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", strict.id)
    assert result.as_dict() == {"active": 1, "incomplete": 1, "changed": 1}
    marked = await lake.collections.get(READER, view.collection.id)
    assert marked.collection.state is State.INCOMPLETE and marked.collection.version == 3
    assert marked.problems
    kept = await lake.collections.get(READER, untouched.collection.id)
    assert kept.collection.version == 2
    repaired = await lake.collections.update(
        CONTRIBUTOR, view.collection.id, 3, Update(metadata_patch={"mission": "solo"})
    )
    assert repaired.collection.state is State.ACTIVE
    _, back = await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", base)
    assert back.changed == 0
    actions = [e.action for e in seeded.store.state.audit if e.object_id == view.collection.id]
    assert Action.COLLECTION_MARK_INCOMPLETE in actions
    assert Action.COLLECTION_MARK_ACTIVE in actions


async def test_incompatible_override_makes_a_collection_incomplete(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    override = {"type": "object", "properties": {"mission": {"type": "integer"}}}
    await lake.collections.update(
        CONTRIBUTOR, view.collection.id, 2, Update(schema_override=override)
    )
    base = (await lake.schemas.list(READER, None, None, None)).items[0].id
    strict = await lake.schemas.publish(
        CATALOG_ADMIN.__class__("bob", "Bob", frozenset({"helio-org-admins"})),
        "helio",
        "strict",
        base,
        {"type": "object", "properties": {"mission": {"type": "string"}}, "required": ["mission"]},
    )
    _, result = await lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", strict.id)
    assert result.incomplete == 1


async def test_search_matches_text_labels_and_states(seeded: World) -> None:
    lake = seeded.lake
    await active(seeded, "alpha", {**VALID_METADATA, "labels": {"site": "a"}})
    await active(seeded, "beta", {"title": "Beta", "description": "other", "labels": {"site": "b"}})
    await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "gamma")
    names = lambda page: [v.collection.name for v in page.items]  # noqa: E731
    assert names(await lake.collections.search(READER, "heliophysics", Search(q="BETA"))) == [
        "beta"
    ]
    assert names(
        await lake.collections.search(READER, "heliophysics", Search(labels=(("site", "a"),)))
    ) == ["alpha"]
    everything = Search(states=frozenset(State))
    assert names(await lake.collections.search(READER, "heliophysics", everything)) == [
        "alpha",
        "beta",
    ]
    assert names(await lake.collections.search(CONTRIBUTOR, "heliophysics", everything)) == [
        "alpha",
        "beta",
        "gamma",
    ]
    page = await lake.collections.search(READER, "heliophysics", Search(), limit=1)
    rest = await lake.collections.search(READER, "heliophysics", Search(), cursor=page.next_cursor)
    assert names(rest) == ["beta"]


async def test_deletion_rules(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    cid = view.collection.id
    with pytest.raises(Forbidden):
        await lake.collections.delete(OTHER_CONTRIBUTOR, cid, 2)
    await lake.commits.commit(
        CONTRIBUTOR, cid, CommitRequest(2, (FileAdd("a.txt", 1, SHA),), (), "host")
    )
    with pytest.raises(CollectionNotEmpty):
        await lake.collections.delete(CONTRIBUTOR, cid, 3)
    with pytest.raises(VersionConflict):
        await lake.collections.delete(CONTRIBUTOR, cid, 2)
    await lake.commits.commit(CONTRIBUTOR, cid, CommitRequest(3, (), ("a.txt",), "host"))
    await lake.collections.delete(CATALOG_ADMIN, cid, 4)
    with pytest.raises(NotFound):
        await lake.collections.get(CONTRIBUTOR, cid)
    other = await active(seeded, "own")
    await lake.collections.delete(CONTRIBUTOR, other.collection.id, 2)


async def test_sidecar_is_canonical_and_absent_for_drafts(seeded: World) -> None:
    lake = seeded.lake
    view = await active(seeded)
    sidecar = await lake.collections.sidecar(READER, view.collection.id)
    assert sidecar.endswith(b"\n")
    assert b'"identifier":"heliophysics.solar-wind.run7"' in sidecar
    assert render_sidecar(view) == sidecar
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    with pytest.raises(Conflict):
        await lake.collections.sidecar(CONTRIBUTOR, draft.collection.id)


def test_merge_patch_follows_rfc_7396() -> None:
    document = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1]}
    patched = merge_patch(document, {"a": None, "b": {"c": None, "x": 1}, "e": [2], "n": {"m": 1}})
    assert patched == {"b": {"d": 3, "x": 1}, "e": [2], "n": {"m": 1}}
    assert document == {"a": 1, "b": {"c": 2, "d": 3}, "e": [1]}
    assert merge_patch({"a": 1}, {"a": {"b": 1}}) == {"a": {"b": 1}}


def test_metadata_size_is_limited() -> None:
    with pytest.raises(MetadataInvalid) as raised:
        check_metadata({"x": "a" * (1024 * 1024)})
    assert raised.value.context["problems"][0]["rule"] == "size"


async def test_a_collection_stays_readable_when_a_new_catalog_schema_conflicts_with_its_override(
    seeded: World,
) -> None:
    lake = seeded.lake
    view = await active(seeded)
    override = {"type": "object", "properties": {"run": {"type": "integer"}}}
    await lake.collections.update(
        CONTRIBUTOR,
        view.collection.id,
        2,
        Update(metadata_patch={"run": 7}, schema_override=override),
    )
    page = await lake.schemas.list(PLATFORM_ADMIN, None, None, None)
    base = next(e.id for e in page.items if e.name == BASE_SCHEMA_NAME)
    clashing = {"type": "object", "properties": {"run": {"type": "string"}}, "required": ["run"]}
    entry = await lake.schemas.publish(ORG_ADMIN, "helio", "clash", base, clashing)
    await lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", entry.id)
    read = await lake.collections.get(READER, view.collection.id)
    assert [p["rule"] for p in read.problems] == ["schema_incompatible"]


async def test_a_dry_run_delete_checks_rights_and_version_but_changes_nothing(
    seeded: World,
) -> None:
    lake = seeded.lake
    view = await active(seeded)
    collection_id = view.collection.id
    await lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, (FileAdd("a", 1, SHA),), (), "h")
    )
    with pytest.raises(Forbidden):
        await lake.collections.delete(OTHER_CONTRIBUTOR, collection_id, 3, dry_run=True)
    with pytest.raises(VersionConflict):
        await lake.collections.delete(CONTRIBUTOR, collection_id, 2, dry_run=True)
    await lake.collections.delete(CONTRIBUTOR, collection_id, 3, dry_run=True)
    await lake.collections.delete(CATALOG_ADMIN, collection_id, 3, dry_run=True)
    assert (await lake.collections.get(READER, collection_id)).collection.file_count == 1
