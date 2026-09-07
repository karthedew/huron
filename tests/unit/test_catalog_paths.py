"""Path construction and parsing round-trip for the shared org/project/dataset layout.

Covers ``revision_dir``/``parse_revision_dir`` (round trip, and rejection of
paths outside the root, old-layout paths, wrong-kind segments, bad revision
numbers and malformed ids in every component), ``dataset_layer_dir``,
single-source vs. fused ``product_dir`` placement, ``release_tag_file`` and
its tag rule, ``generation_file``'s range and zero-padding, ``staging_dir``,
``validate_slug``'s pattern rule and ``validate_org_slug``'s reserved-route
rule.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from huron.pkg.catalog.errors import PathRuleViolation
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.layers import Layer
from huron.pkg.catalog.models import EntityRef
from huron.pkg.catalog.paths import (
    ORG_PROJECT_SLUG_MAX,
    dataset_dir,
    dataset_layer_dir,
    generation_file,
    organization_dir,
    parse_revision_dir,
    product_dir,
    project_dir,
    release_tag_file,
    revision_dir,
    staging_dir,
    validate_org_slug,
    validate_slug,
)

pytestmark = pytest.mark.unit

ROOT = PurePosixPath("/data")


def _entity(slug: str) -> EntityRef:
    """Build an ``EntityRef`` with a fresh id and the given slug."""
    return EntityRef(uuid7(), slug)


class Hierarchy:
    """A related organization, project and dataset, each with a fresh id and a fixed slug."""

    def __init__(self) -> None:
        self.organization = _entity("nuclear-engineering")
        self.project = _entity("huron-shielding-study")
        self.dataset = _entity("reactor-shielding-sweep")


def test_revision_dir_nests_raw_and_revision_under_the_dataset() -> None:
    """A revision directory nests as ``{dataset dir}/raw/revision/{NNNNNN}--{id}``."""
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


def test_organization_dir_accepts_a_frozen_entity_ref() -> None:
    """``organization_dir`` builds the slug--uuid directory from a frozen ``EntityRef``."""
    organization = _entity("nuclear-engineering")
    path = organization_dir(ROOT, organization)
    assert path == ROOT / "organization" / f"{organization.slug}--{organization.id.hex}"


def test_parse_revision_dir_round_trips_through_revision_dir() -> None:
    """``parse_revision_dir`` recovers exactly the identity ``revision_dir`` was built from."""
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
    """A path outside the given root is refused by ``parse_revision_dir``."""
    hierarchy = Hierarchy()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 1, uuid7()
    )
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(PurePosixPath("/somewhere-else"), path)


def test_parse_revision_dir_rejects_the_old_layout_without_a_raw_segment() -> None:
    """A pre-existing-layout path with no ``raw`` segment is refused, not silently resolved."""
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
    """A path whose ``dataset`` kind segment has been renamed to something else is refused."""
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
    """A revision number that is zero, out of range, unpadded, or non-numeric is refused."""
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
    """A revision id that is too short, upper-case, or not hexadecimal is refused."""
    hierarchy = Hierarchy()
    base = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    path = base / "raw" / "revision" / f"000042--{revision_hex}"
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, path)


@pytest.mark.parametrize("layer", [Layer.RAW, Layer.BRONZE, Layer.SILVER, Layer.GOLD])
def test_dataset_layer_dir_sits_under_the_dataset(layer: Layer) -> None:
    """Each layer's directory is the dataset directory's child named after the layer code."""
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
    """``dataset_layer_dir`` accepts a plain layer string in place of a ``Layer`` member."""
    hierarchy = Hierarchy()
    path = dataset_layer_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "gold"
    )
    assert path.name == "gold"


def test_dataset_layer_dir_rejects_an_unknown_layer() -> None:
    """``dataset_layer_dir`` refuses a layer string that names no real layer."""
    hierarchy = Hierarchy()
    with pytest.raises(PathRuleViolation):
        dataset_layer_dir(
            ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "platinum"
        )


def test_single_source_product_lives_under_its_dataset() -> None:
    """A single-source product's directory sits under its dataset's gold segment."""
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
    """A fused product with no dataset sits under the project's product segment instead."""
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
    """The same product's single-source and fused directories never collide on one path."""
    hierarchy = Hierarchy()
    product = _entity("shielding-dose-response")
    single_source = product_dir(
        ROOT, hierarchy.organization, hierarchy.project, product, dataset=hierarchy.dataset
    )
    fused = product_dir(ROOT, hierarchy.organization, hierarchy.project, product)
    assert single_source != fused


def test_release_tag_file_is_a_sibling_of_raw_not_nested_inside_it() -> None:
    """A release tag file sits beside raw under releases/, never nested inside raw."""
    hierarchy = Hierarchy()
    tag_path = release_tag_file(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "v1.0"
    )
    base = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    assert tag_path == base / "releases" / "v1.0.json"
    assert "raw" not in tag_path.relative_to(base).parts


def test_staging_dir_sits_at_the_data_root() -> None:
    """An ingest session's staging directory sits at the data root, under ``.staging``."""
    ingest_id = uuid7()
    assert staging_dir(ROOT, ingest_id) == ROOT / ".staging" / ingest_id.hex


@pytest.mark.parametrize("slug", ["auth", "login", "logout", "signup", "settings", "ingestion"])
def test_validate_org_slug_reserves_root_routes(slug: str) -> None:
    """An organization slugged like an application route would be unreachable."""
    with pytest.raises(PathRuleViolation):
        validate_org_slug(slug)


def test_validate_org_slug_accepts_an_ordinary_slug() -> None:
    """An ordinary, non-reserved organization slug passes validation without raising."""
    validate_org_slug("nuclear-engineering")


@pytest.mark.parametrize(
    "slug",
    [
        "Bad Slug",  # breaks the lower-case pattern
        "a--b",  # contains the slug/id separator
        "a" * (ORG_PROJECT_SLUG_MAX + 1),  # longer than max_len
    ],
)
def test_validate_slug_rejects_a_slug_that_could_not_serve_as_a_path_component(slug: str) -> None:
    """A slug breaking the pattern, holding the separator, or over length is refused."""
    with pytest.raises(PathRuleViolation):
        validate_slug(slug, ORG_PROJECT_SLUG_MAX)


def test_release_tag_file_rejects_a_tag_that_could_not_be_a_file_name() -> None:
    """A tag that fails the tag pattern is refused before any release path is built."""
    hierarchy = Hierarchy()
    with pytest.raises(PathRuleViolation):
        release_tag_file(
            ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, "NOT A TAG"
        )


@pytest.mark.parametrize("number", [0, 1_000_000])
def test_revision_dir_rejects_a_revision_number_outside_the_legal_range(number: int) -> None:
    """revision_dir refuses a revision number outside 1 to 999,999."""
    hierarchy = Hierarchy()
    with pytest.raises(PathRuleViolation):
        revision_dir(
            ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, number, uuid7()
        )


@pytest.mark.parametrize("generation", [0, 1_000_000])
def test_generation_file_rejects_a_generation_outside_the_legal_range(generation: int) -> None:
    """generation_file refuses a generation number outside 1 to 999,999."""
    hierarchy = Hierarchy()
    entity_dir = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    with pytest.raises(PathRuleViolation):
        generation_file(entity_dir, generation)


def test_generation_file_zero_pads_a_valid_generation_number() -> None:
    """A valid generation number returns the entity's zero-padded generations file path."""
    hierarchy = Hierarchy()
    entity_dir = dataset_dir(ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset)
    assert generation_file(entity_dir, 42) == entity_dir / "generations" / "000042.json"


def test_parse_revision_dir_rejects_an_organization_component_with_no_separator() -> None:
    """An organization component with no ``--`` separator is refused, not just the revision one."""
    hierarchy = Hierarchy()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 1, uuid7()
    )
    relative_parts = list(path.relative_to(ROOT).parts)
    relative_parts[1] = "no-separator-here"
    mangled = ROOT.joinpath(*relative_parts)
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, mangled)


@pytest.mark.parametrize(
    "organization_id_hex",
    [
        "a" * 31,  # too short
        "A" * 32,  # uppercase
        "g" * 32,  # not hex
    ],
)
def test_parse_revision_dir_rejects_an_organization_component_with_a_malformed_id(
    organization_id_hex: str,
) -> None:
    """An organization component whose id half is not 32 lower-case hex digits is refused."""
    hierarchy = Hierarchy()
    path = revision_dir(
        ROOT, hierarchy.organization, hierarchy.project, hierarchy.dataset, 1, uuid7()
    )
    relative_parts = list(path.relative_to(ROOT).parts)
    relative_parts[1] = f"{hierarchy.organization.slug}--{organization_id_hex}"
    mangled = ROOT.joinpath(*relative_parts)
    with pytest.raises(PathRuleViolation):
        parse_revision_dir(ROOT, mangled)
