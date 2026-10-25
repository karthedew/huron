"""Hierarchy, layer and product paths validate identities and generation bounds."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from huron.core.catalog.layers import Layer
from huron.core.catalog.paths import (
    dataset_dir,
    dataset_layer_dir,
    generation_file,
    organization_dir,
    product_dir,
    project_dir,
)
from huron.core.catalog.types import EntityRef
from huron.core.foundation.errors import PathRuleViolation
from huron.core.foundation.identifiers import uuid7
from huron.core.foundation.names import ORG_PROJECT_SLUG_MAX, validate_org_slug, validate_slug

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


def test_organization_dir_accepts_a_frozen_entity_ref() -> None:
    """``organization_dir`` builds the slug--uuid directory from a frozen ``EntityRef``."""
    organization = _entity("nuclear-engineering")
    path = organization_dir(ROOT, organization)
    assert path == ROOT / "organization" / f"{organization.slug}--{organization.id.hex}"


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


@pytest.mark.parametrize("slug", ["auth", "login", "logout", "signup", "settings", "polaris"])
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
