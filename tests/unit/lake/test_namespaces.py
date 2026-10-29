"""Namespaces: the recursive tree, sibling exclusion and configuration."""

import pytest

from huron.core.lake.errors import NameTaken
from huron.core.lake.namespaces.errors import NamespaceNotEmpty
from huron.pkg.errors import Forbidden, NotFound
from huron.schema.naming import NamingError
from tests.support.lake import CATALOG_ADMIN, CONTRIBUTOR, READER, VALID_METADATA, World


async def test_namespaces_nest_to_any_depth(seeded: World) -> None:
    ns = seeded.lake.namespaces
    parent = "solar-wind"
    for depth in range(11):
        view = await ns.create(CATALOG_ADMIN, "heliophysics", parent, f"l{depth}")
        parent = view.namespace.path
    assert parent.count(".") == 11
    deepest = await ns.get(READER, "heliophysics", parent)
    assert deepest.identifier == f"heliophysics.{parent}"
    assert deepest.disk_path.startswith("helio/heliophysics/solar-wind/l0/")
    assert deepest.as_dict()["parent"] == parent.rsplit(".", 1)[0]


async def test_children_are_listed_in_name_order(seeded: World) -> None:
    ns = seeded.lake.namespaces
    for name in ("b", "a", "c"):
        await ns.create(CATALOG_ADMIN, "heliophysics", "solar-wind", name)
    page = await ns.children(READER, "heliophysics", "solar-wind", limit=2)
    assert [v.namespace.name for v in page.items] == ["a", "b"]
    rest = await ns.children(READER, "heliophysics", "solar-wind", cursor=page.next_cursor)
    assert [v.namespace.name for v in rest.items] == ["c"]
    roots = await ns.children(READER, "heliophysics")
    assert [v.namespace.name for v in roots.items] == ["solar-wind"]
    assert roots.items[0].namespace_count == 3


async def test_creation_checks_privilege_parent_and_names(seeded: World) -> None:
    ns = seeded.lake.namespaces
    with pytest.raises(Forbidden):
        await ns.create(CONTRIBUTOR, "heliophysics", "", "x")
    with pytest.raises(NotFound):
        await ns.create(CATALOG_ADMIN, "heliophysics", "missing", "x")
    with pytest.raises(NamingError):
        await ns.create(CATALOG_ADMIN, "heliophysics", "", "Bad")
    with pytest.raises(NamingError):
        await ns.create(CATALOG_ADMIN, "heliophysics", ".".join(["a" * 60] * 4), "x")
    with pytest.raises(NameTaken):
        await ns.create(CATALOG_ADMIN, "heliophysics", "", "solar-wind")


async def test_a_namespace_cannot_share_a_name_with_a_sibling_collection(seeded: World) -> None:
    await seeded.lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "run7")
    with pytest.raises(NameTaken):
        await seeded.lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "run7")


async def test_non_empty_namespaces_cannot_be_deleted(seeded: World) -> None:
    ns = seeded.lake.namespaces
    await ns.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "child")
    with pytest.raises(NamespaceNotEmpty):
        await ns.delete(CATALOG_ADMIN, "heliophysics", "solar-wind")
    await ns.delete(CATALOG_ADMIN, "heliophysics", "solar-wind.child")
    await seeded.lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "draft")
    with pytest.raises(NamespaceNotEmpty) as raised:
        await ns.delete(CATALOG_ADMIN, "heliophysics", "solar-wind")
    assert raised.value.context == {"namespace_count": 0, "collection_count": 1}


async def test_configure_toggles_collections_only_when_empty(seeded: World) -> None:
    ns = seeded.lake.namespaces
    view = await ns.configure(CATALOG_ADMIN, "heliophysics", "solar-wind", True)
    assert view.namespace.version == 1
    await seeded.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", VALID_METADATA
    )
    with pytest.raises(NamespaceNotEmpty):
        await ns.configure(CATALOG_ADMIN, "heliophysics", "solar-wind", False)
    await ns.create(CATALOG_ADMIN, "heliophysics", "", "archive", True)
    closed = await ns.configure(CATALOG_ADMIN, "heliophysics", "archive", False)
    assert closed.namespace.collections_allowed is False
    assert closed.namespace.version == 2


async def test_collection_counts_hide_drafts_from_callers_who_cannot_create(
    seeded: World,
) -> None:
    lake = seeded.lake
    await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "secret")
    draft = await lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
    )
    await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)
    assert (
        await lake.namespaces.get(CONTRIBUTOR, "heliophysics", "solar-wind")
    ).collection_count == 2
    assert (await lake.namespaces.get(READER, "heliophysics", "solar-wind")).collection_count == 1
    children = await lake.namespaces.children(READER, "heliophysics", "")
    assert [view.collection_count for view in children.items] == [1]
