"""Path construction and parsing for the shared organization/project/dataset
layout: raw revisions, per-dataset layer segments, and Gold products split
by provenance scope."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from huron.pkg.catalog.errors import PathRuleViolation
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.layers import Layer
from huron.pkg.catalog.models import EntityRef
from huron.pkg.catalog.paths import (
    dataset_dir,
    dataset_layer_dir,
    parse_revision_dir,
    product_dir,
    project_dir,
    release_tag_file,
    revision_dir,
    staging_dir,
    validate_org_slug,
)

pytestmark = pytest.mark.unit

ROOT = PurePosixPath("/data")


def _entity(slug: str) -> EntityRef:
    return EntityRef(uuid7(), slug)


class Hierarchy:
    def __init__(self) -> None:
        self.organization = _entity("nuclear-engineering")
        self.project = _entity("huron-shielding-study")
        self.dataset = _entity("reactor-shielding-sweep")


def test_revision_dir_nests_raw_and_revision_under_the_dataset() -> None:
    hierarchy = Hierarchy()
    revision_id = uuid7()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 42, revision_id
    )
    expected_tail = (
        dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
        / "raw"
        / "revision"
        / f"000042--{revision_id.hex}"
    )
    assert path == expected_tail


def test_parse_revision_dir_round_trips_through_revision_dir() -> None:
    hierarchy = Hierarchy()
    revision_id = uuid7()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 42, revision_id
    )
    parsed = parse_revision_dir(ROOT, path)
    assert parsed.org_slug == hierarchy.organization.slug
    assert parsed.org_id == hierarchy.organization.id
    assert parsed.project_slug == hierarchy.project.slug
    assert parsed.project_id == hierarchy.project.id
    assert parsed.dataset_slug == hierarchy.dataset.slug
    assert parsed.dataset_id == hierarchy.dataset.id
    assert parsed.revision_number == 42
    assert parsed.revision_id == revision_id


def test_parse_revision_dir_rejects_a_path_outside_the_root() -> None:
    hierarchy = Hierarchy()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 1, uuid7()
    )
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(PurePosixPath("/somewhere-else"), path)


def test_parse_revision_dir_rejects_the_old_layout_without_a_raw_segment() -> None:
    """A revision directory built under the pre-existing scheme, where raw sat
    directly at the data root and a dataset's revision hung straight off it,
    must be rejected rather than silently resolved to the wrong thing."""
    hierarchy = Hierarchy()
    revision_id = uuid7()
    old_style = (
        dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
        / "revision"
        / f"000042--{revision_id.hex}"
    )
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, old_style)


def test_parse_revision_dir_rejects_a_wrong_kind_segment() -> None:
    hierarchy = Hierarchy()
    revision_id = uuid7()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 1, revision_id
    )
    relative_parts = list(path.relative_to(ROOT).parts)
    relative_parts[4] = "team"  # was "dataset"
    mangled = ROOT.joinpath(*relative_parts)
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, mangled)


@pytest.mark.parametrize(
    "revision_component",
    [
        "000000--" + "a" * 32,  # revision number 0
        "1000000--" + "a" * 32,  # revision number out of range
        "42--" + "a" * 32,  # not zero-padded to 6 digits
        "abcdef--" + "a" * 32,  # non-numeric revision number
    ],
)
def test_parse_revision_dir_rejects_a_bad_revision_number(revision_component: str) -> None:
    hierarchy = Hierarchy()
    base = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    path = base / "raw" / "revision" / revision_component
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, path)


@pytest.mark.parametrize(
    "revision_hex",
    [
        "a" * 31,  # too short
        "A" * 32,  # uppercase
        "g" * 32,  # not hex
    ],
)
def test_parse_revision_dir_rejects_a_malformed_uuid(revision_hex: str) -> None:
    hierarchy = Hierarchy()
    base = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    path = base / "raw" / "revision" / f"000042--{revision_hex}"
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, path)


@pytest.mark.parametrize("layer", [Layer.RAW, Layer.BRONZE, Layer.SILVER, Layer.GOLD])
def test_dataset_layer_dir_sits_under_the_dataset(layer: Layer) -> None:
    hierarchy = Hierarchy()
    path = dataset_layer_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, layer
    )
    assert (
        path
        == dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
        / layer.value
    )


def test_dataset_layer_dir_accepts_a_plain_string_layer() -> None:
    hierarchy = Hierarchy()
    path = dataset_layer_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "gold"
    )
    assert path.name == "gold"


def test_dataset_layer_dir_rejects_an_unknown_layer() -> None:
    hierarchy = Hierarchy()
    with pytest.raises(PathRuleViolation):
        dataset_layer_dir(
            ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "platinum"
        )


def test_single_source_product_lives_under_its_dataset() -> None:
    hierarchy = Hierarchy()
    product = _entity("shielding-dose-response")
    path = product_dir(
        ROOT, hierarchy.organization, hierarchy.project, product, dataset=hierarchy.dataset
    )
    expected = (
        dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
        / "gold"
        / f"{product.slug}--{product.id.hex}"
    )
    assert path == expected


def test_fused_product_lives_under_the_project() -> None:
    hierarchy = Hierarchy()
    product = _entity("shielding-dose-response")
    path = product_dir(ROOT, hierarchy.organization, hierarchy.project, product)
    expected = (
        project_dir(ROOT, hierarchy.organization, hierarchy.project)
        / "product"
        / f"{product.slug}--{product.id.hex}"
    )
    assert path == expected


def test_single_source_and_fused_products_never_collide() -> None:
    hierarchy = Hierarchy()
    product = _entity("shielding-dose-response")
    single_source = product_dir(
        ROOT, hierarchy.organization, hierarchy.project, product, dataset=hierarchy.dataset
    )
    fused = product_dir(ROOT, hierarchy.organization, hierarchy.project, product)
    assert single_source != fused


def test_release_tag_file_is_a_sibling_of_raw_not_nested_inside_it() -> None:
    hierarchy = Hierarchy()
    tag_path = release_tag_file(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "v1.0"
    )
    base = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    assert tag_path == base / "releases" / "v1.0.json"
    assert "raw" not in tag_path.relative_to(base).parts


def test_staging_dir_sits_at_the_data_root() -> None:
    ingest_id = uuid7()
    assert staging_dir(ROOT, ingest_id) == ROOT / ".staging" / ingest_id.hex


@pytest.mark.parametrize("slug", ["auth", "login", "logout", "signup", "settings", "ingestion"])
def test_validate_org_slug_reserves_root_routes(slug: str) -> None:
    """An organization slugged like an application route would be unreachable."""
    with pytest.raises(PathRuleViolation):
        validate_org_slug(slug)


def test_validate_org_slug_accepts_an_ordinary_slug() -> None:
    validate_org_slug("nuclear-engineering")
