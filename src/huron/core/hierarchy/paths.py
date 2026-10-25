"""Hierarchy generations and shared cross-layer layout declarations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.foundation.errors import PathRuleViolation
from huron.core.foundation.names import (
    DATASET_SLUG_MAX,
    ORG_PROJECT_SLUG_MAX,
    Slugged,
    validate_org_slug,
    validate_slug,
)

from .layers import Layer

if TYPE_CHECKING:
    from pathlib import PurePosixPath


def organization_dir(root: PurePosixPath, organization: Slugged) -> PurePosixPath:
    """Build an organization's stable directory.

    Args:
        root: Data root.
        organization: Organization identity and slug.

    Returns:
        The organization directory after validating its slug.
    """
    validate_org_slug(organization.slug)
    return root / "organization" / f"{organization.slug}--{organization.id.hex}"


def project_dir(root: PurePosixPath, organization: Slugged, project: Slugged) -> PurePosixPath:
    """Build a project's stable directory.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Project identity and slug.

    Returns:
        The project directory after validating all slugs.
    """
    validate_slug(project.slug, ORG_PROJECT_SLUG_MAX)
    return organization_dir(root, organization) / "project" / f"{project.slug}--{project.id.hex}"


def dataset_dir(
    root: PurePosixPath, organization: Slugged, project: Slugged, dataset: Slugged
) -> PurePosixPath:
    """Build a dataset's stable directory.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Owning project.
        dataset: Dataset identity and slug.

    Returns:
        The dataset directory after validating all slugs.
    """
    validate_slug(dataset.slug, DATASET_SLUG_MAX)
    return (
        project_dir(root, organization, project) / "dataset" / f"{dataset.slug}--{dataset.id.hex}"
    )


def dataset_layer_dir(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    dataset: Slugged,
    layer: Layer | str,
) -> PurePosixPath:
    """Build the layer directory beneath a dataset.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Owning project.
        dataset: Dataset identity and slug.
        layer: Layer enum or its string code.

    Returns:
        The layer directory.

    Raises:
        PathRuleViolation: If the layer is unknown.
    """
    try:
        resolved = layer if isinstance(layer, Layer) else Layer(layer)
    except ValueError as exc:
        raise PathRuleViolation(f"unknown layer: {layer!r}") from exc
    return dataset_dir(root, organization, project, dataset) / resolved.value


def product_dir(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    product: Slugged,
    dataset: Slugged | None = None,
) -> PurePosixPath:
    """Build a dataset-scoped or fused project-scoped Gold product directory.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Owning project.
        product: Product identity and slug.
        dataset: Owning dataset, or None for a fused product.

    Returns:
        The product directory.
    """
    validate_slug(product.slug, ORG_PROJECT_SLUG_MAX)
    if dataset is not None:
        return (
            dataset_dir(root, organization, project, dataset)
            / "gold"
            / f"{product.slug}--{product.id.hex}"
        )
    return (
        project_dir(root, organization, project) / "product" / f"{product.slug}--{product.id.hex}"
    )


def generation_file(entity_dir: PurePosixPath, generation: int) -> PurePosixPath:
    """Build one immutable generation document's path.

    Args:
        entity_dir: Hierarchy entity directory.
        generation: Generation number, 1 through 999,999.

    Returns:
        Its numbered JSON path.

    Raises:
        PathRuleViolation: If the generation is outside the representable range.
    """
    if not 1 <= generation <= 999_999:
        raise PathRuleViolation(f"generation out of range: {generation}")
    return entity_dir / "generations" / f"{generation:06d}.json"
