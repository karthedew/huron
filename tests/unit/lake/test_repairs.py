"""Repair plans: the directories a repair acts on, read from the rows, and who may repair."""

import uuid

import pytest

from huron.core.lake.collections.metadata import render_sidecar
from huron.core.lake.repairs import Level, PlannedDirectory, PlannedRow, RepairPlan
from huron.core.security.rbac import Actor
from huron.pkg.errors import Conflict, Forbidden, Invalid, NotFound
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    PLATFORM_ADMIN,
    READER,
    STRANGER,
    World,
    settled_collection,
)

CATALOG = "helio/heliophysics"


@pytest.fixture
async def tree(seeded: World) -> World:
    """The seeded lake with the namespaces ``solar-wind.inner``, ``solar`` and ``aurora``, the
    collections ``solar-wind.run7``, ``solar-wind.inner.deep`` and ``solar.flare``, and a draft
    in ``solar-wind``.
    """
    lake = seeded.lake
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "inner", True)
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "solar", True)
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "aurora")
    await settled_collection(lake)
    await settled_collection(lake, "deep", "solar-wind.inner")
    await settled_collection(lake, "flare", "solar")
    await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "draft")
    return seeded


def paths(plan: RepairPlan) -> list[tuple[str, Level]]:
    return [(directory.path, directory.level) for directory in plan.directories]


async def test_a_catalog_plan_holds_the_catalog_directory(tree: World) -> None:
    plan = await tree.lake.repairs.plan(CATALOG_ADMIN, "heliophysics", "heliophysics", False)
    catalog = await tree.lake.catalogs.get(CATALOG_ADMIN, "heliophysics")
    directory = PlannedDirectory(CATALOG, Level.CATALOG, catalog.catalog.id)
    assert plan == RepairPlan((directory,), None)
    assert plan.catalog == directory


async def test_a_recursive_plan_holds_every_namespace_and_settled_collection(tree: World) -> None:
    await tree.lake.catalogs.set_share_group(ORG_ADMIN, "heliophysics", "helio-readers")
    plan = await tree.lake.repairs.plan(CATALOG_ADMIN, "heliophysics", "heliophysics", True)
    assert plan.share_group == "helio-readers"
    assert plan.catalog == plan.directories[0]
    assert paths(plan) == [
        (CATALOG, Level.CATALOG),
        (f"{CATALOG}/aurora", Level.NAMESPACE),
        (f"{CATALOG}/solar", Level.NAMESPACE),
        (f"{CATALOG}/solar/flare", Level.COLLECTION),
        (f"{CATALOG}/solar-wind", Level.NAMESPACE),
        (f"{CATALOG}/solar-wind/inner", Level.NAMESPACE),
        (f"{CATALOG}/solar-wind/inner/deep", Level.COLLECTION),
        (f"{CATALOG}/solar-wind/run7", Level.COLLECTION),
    ]


@pytest.mark.parametrize(
    ("target", "recursive", "expected"),
    [
        (
            "heliophysics.solar-wind.inner",
            False,
            [
                (CATALOG, Level.CATALOG),
                (f"{CATALOG}/solar-wind", Level.NAMESPACE),
                (f"{CATALOG}/solar-wind/inner", Level.NAMESPACE),
            ],
        ),
        (
            "heliophysics.solar-wind",
            True,
            [
                (CATALOG, Level.CATALOG),
                (f"{CATALOG}/solar-wind", Level.NAMESPACE),
                (f"{CATALOG}/solar-wind/inner", Level.NAMESPACE),
                (f"{CATALOG}/solar-wind/inner/deep", Level.COLLECTION),
                (f"{CATALOG}/solar-wind/run7", Level.COLLECTION),
            ],
        ),
        (
            "heliophysics.solar",
            True,
            [
                (CATALOG, Level.CATALOG),
                (f"{CATALOG}/solar", Level.NAMESPACE),
                (f"{CATALOG}/solar/flare", Level.COLLECTION),
            ],
        ),
        (
            "heliophysics.solar-wind.inner.deep",
            True,
            [
                (CATALOG, Level.CATALOG),
                (f"{CATALOG}/solar-wind", Level.NAMESPACE),
                (f"{CATALOG}/solar-wind/inner", Level.NAMESPACE),
                (f"{CATALOG}/solar-wind/inner/deep", Level.COLLECTION),
            ],
        ),
    ],
    ids=["namespace", "namespace-recursive", "sibling-prefix", "collection"],
)
async def test_a_plan_runs_from_the_catalog_down_to_its_target(
    tree: World, target: str, recursive: bool, expected: list[tuple[str, Level]]
) -> None:
    plan = await tree.lake.repairs.plan(CATALOG_ADMIN, "heliophysics", target, recursive)
    assert paths(plan) == expected


@pytest.mark.parametrize(
    ("target", "error", "code"),
    [
        ("geophysics.x", Invalid, "REQUEST_INVALID"),
        ("heliophysics-x", Invalid, "REQUEST_INVALID"),
        ("heliophysics.nowhere", NotFound, "NOT_FOUND"),
        ("heliophysics.solar-wind.draft", Conflict, "STATE_CONFLICT"),
    ],
    ids=["other-catalog", "name-prefix", "unknown", "draft"],
)
async def test_a_target_must_be_a_directory_of_the_catalog(
    tree: World, target: str, error: type[Exception], code: str
) -> None:
    with pytest.raises(error) as refused:
        await tree.lake.repairs.plan(CATALOG_ADMIN, "heliophysics", target, False)
    assert getattr(refused.value, "code", None) == code


@pytest.mark.parametrize(
    ("actor", "error"),
    [(CONTRIBUTOR, Forbidden), (READER, Forbidden), (STRANGER, NotFound)],
    ids=["contributor", "reader", "stranger"],
)
async def test_a_catalog_repair_needs_namespace_configure(
    tree: World, actor: Actor, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await tree.lake.repairs.plan(actor, "heliophysics", "heliophysics", False)


async def test_the_planned_rows_are_read_again(tree: World) -> None:
    lake = tree.lake
    plan = await lake.repairs.plan(CATALOG_ADMIN, "heliophysics", "heliophysics", True)
    by_path = {directory.path: directory for directory in plan.directories}
    run7 = by_path[f"{CATALOG}/solar-wind/run7"]
    view = await lake.collections.get(READER, run7.id)
    assert await lake.repairs.expected(run7) == PlannedRow(render_sidecar(view))
    assert await lake.repairs.expected(by_path[CATALOG]) == PlannedRow()
    aurora = by_path[f"{CATALOG}/aurora"]
    assert await lake.repairs.expected(aurora) == PlannedRow()
    await lake.namespaces.delete(CATALOG_ADMIN, "heliophysics", "aurora")
    await lake.collections.delete(CONTRIBUTOR, run7.id, 2)
    assert await lake.repairs.expected(aurora) is None
    assert await lake.repairs.expected(run7) is None
    gone = PlannedDirectory("helio/gone", Level.CATALOG, uuid.uuid4())
    assert await lake.repairs.expected(gone) is None


async def test_an_organization_plan_holds_its_directory_while_its_row_is_there(
    tree: World,
) -> None:
    repairs = tree.lake.repairs
    await tree.lake.organizations.create(PLATFORM_ADMIN, "geo")
    plan = await repairs.organization(PLATFORM_ADMIN, "geo")
    [geo] = plan.directories
    assert (geo.path, geo.level, plan.share_group, plan.catalog) == (
        "geo",
        Level.ORGANIZATION,
        None,
        None,
    )
    assert await repairs.expected(geo) == PlannedRow()
    await tree.lake.organizations.delete(PLATFORM_ADMIN, "geo")
    assert await repairs.expected(geo) is None


async def test_an_organization_repair_needs_catalog_grant_admin(tree: World) -> None:
    repairs = tree.lake.repairs
    helio = await tree.lake.organizations.get(ORG_ADMIN, "helio")
    expected = RepairPlan((PlannedDirectory("helio", Level.ORGANIZATION, helio.organization.id),))
    assert await repairs.organization(ORG_ADMIN, "helio") == expected
    assert await repairs.organization(PLATFORM_ADMIN, "helio") == expected
    with pytest.raises(Forbidden):
        await repairs.organization(CATALOG_ADMIN, "helio")
    with pytest.raises(NotFound):
        await repairs.organization(STRANGER, "helio")
