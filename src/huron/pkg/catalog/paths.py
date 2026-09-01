"""The sole constructor and parser for the POSIX layout shared by every layer."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple, Protocol
from uuid import UUID

from .errors import PathRuleViolation
from .layers import Layer

if TYPE_CHECKING:
    from pathlib import PurePosixPath

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
ORG_PROJECT_SLUG_MAX = 62
DATASET_SLUG_MAX = 80

RESERVED_ROOT_SLUGS = frozenset(
    {
        "admin",
        "browse",
        "account",
        "queue",
        "product",
        "snapshot",
        "search",
        "api",
        "auth",
        "login",
        "logout",
        "signup",
        "settings",
        "ingestion",
    }
)


class Slugged(Protocol):
    id: UUID
    slug: str


class RevisionPath(NamedTuple):
    org_slug: str
    org_id: UUID
    project_slug: str
    project_id: UUID
    dataset_slug: str
    dataset_id: UUID
    revision_number: int
    revision_id: UUID


def validate_slug(slug: str, max_len: int) -> None:
    if max_len < 2 or not SLUG.fullmatch(slug) or "--" in slug or len(slug) > max_len:
        raise PathRuleViolation(f"invalid slug: {slug!r}")


def validate_org_slug(slug: str) -> None:
    validate_slug(slug, ORG_PROJECT_SLUG_MAX)
    if slug in RESERVED_ROOT_SLUGS:
        raise PathRuleViolation(f"reserved organization slug: {slug!r}")


def validate_tag(tag: str) -> None:
    if not TAG.fullmatch(tag):
        raise PathRuleViolation(f"invalid release tag: {tag!r}")


def organization_dir(root: PurePosixPath, organization: Slugged) -> PurePosixPath:
    validate_org_slug(organization.slug)
    return root / "organization" / f"{organization.slug}--{organization.id.hex}"


def project_dir(root: PurePosixPath, organization: Slugged, project: Slugged) -> PurePosixPath:
    validate_slug(project.slug, ORG_PROJECT_SLUG_MAX)
    return organization_dir(root, organization) / "project" / f"{project.slug}--{project.id.hex}"


def dataset_dir(
    root: PurePosixPath, organization: Slugged, project: Slugged, dataset: Slugged
) -> PurePosixPath:
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
    """The per-layer segment under a dataset: ``dataset/{...}/{layer}``.

    ``layer`` accepts a plain string as well as a :class:`Layer` member so a
    value fresh off an API request can be validated and turned into a path in
    one step; :class:`Layer` stays the one place the four layer codes are
    spelled out, so this never drifts from ``pkg/catalog/layers.py``.
    """
    try:
        resolved = layer if isinstance(layer, Layer) else Layer(layer)
    except ValueError as exc:
        raise PathRuleViolation(f"unknown layer: {layer!r}") from exc
    return dataset_dir(root, organization, project, dataset) / resolved.value


def revision_dir(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    dataset: Slugged,
    number: int,
    revision_id: UUID,
) -> PurePosixPath:
    if not 1 <= number <= 999_999:
        raise PathRuleViolation(f"revision number out of range: {number}")
    return (
        dataset_dir(root, organization, project, dataset)
        / "raw"
        / "revision"
        / f"{number:06d}--{revision_id.hex}"
    )


def release_tag_file(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    dataset: Slugged,
    tag: str,
) -> PurePosixPath:
    validate_tag(tag)
    return dataset_dir(root, organization, project, dataset) / "releases" / f"{tag}.json"


def product_dir(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    product: Slugged,
    dataset: Slugged | None = None,
) -> PurePosixPath:
    """A Gold product's directory, split by provenance scope.

    The Icechunk repository is the ``repo/`` child of this directory, and a
    tabular product's Iceberg materialization is its ``iceberg/`` sibling, so
    what is returned here is the product, not either representation of it.

    A single-source product sits under the one dataset it derives from
    (``dataset/{...}/gold/{product}``); a fused product has no one dataset to
    sit under, so it sits under the project instead
    (``project/{...}/product/{product}``). Passing ``dataset`` selects which
    case applies - it mirrors ``products.dataset_id`` being set or ``NULL``.
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


def staging_dir(root: PurePosixPath, ingest_id: UUID) -> PurePosixPath:
    return root / ".staging" / ingest_id.hex


def generation_file(entity_dir: PurePosixPath, generation: int) -> PurePosixPath:
    if not 1 <= generation <= 999_999:
        raise PathRuleViolation(f"generation out of range: {generation}")
    return entity_dir / "generations" / f"{generation:06d}.json"


def _split(component: str, max_len: int) -> tuple[str, UUID]:
    slug, separator, hex_id = component.rpartition("--")
    if not separator:
        raise PathRuleViolation(f"unparseable component: {component!r}")
    validate_slug(slug, max_len)
    if len(hex_id) != 32 or hex_id.lower() != hex_id or not re.fullmatch(r"[0-9a-f]{32}", hex_id):
        raise PathRuleViolation(f"invalid path UUID: {hex_id!r}")
    return slug, UUID(hex=hex_id)


def parse_revision_dir(root: PurePosixPath, path: PurePosixPath) -> RevisionPath:
    """Recover the complete identity tuple from an exact revision directory.

    The layout is ``organization/{X}/project/{Y}/dataset/{Z}/raw/revision/{NNNNNN--hex}``
    - nine segments, with the layer (``raw``) breaking what would otherwise be
    a clean kind/value alternation. Anything else, the old eight-segment
    layout included, is rejected rather than guessed at: a stale path left
    over from the earlier scheme must fail loudly, not resolve to the wrong
    dataset.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PathRuleViolation(f"path is outside the data root: {path}") from exc
    parts = relative.parts
    if (
        len(parts) != 9
        or parts[0] != "organization"
        or parts[2] != "project"
        or parts[4] != "dataset"
        or parts[6] != "raw"
        or parts[7] != "revision"
    ):
        raise PathRuleViolation(f"unexpected layout: {relative}")
    org_slug, org_id = _split(parts[1], ORG_PROJECT_SLUG_MAX)
    project_slug, project_id = _split(parts[3], ORG_PROJECT_SLUG_MAX)
    dataset_slug, dataset_id = _split(parts[5], DATASET_SLUG_MAX)
    number_text, separator, revision_hex = parts[8].partition("--")
    if (
        not separator
        or not re.fullmatch(r"[0-9]{6}", number_text)
        or not 1 <= int(number_text) <= 999_999
        or len(revision_hex) != 32
        or revision_hex.lower() != revision_hex
        or not re.fullmatch(r"[0-9a-f]{32}", revision_hex)
    ):
        raise PathRuleViolation(f"invalid revision component: {parts[8]!r}")
    return RevisionPath(
        org_slug,
        org_id,
        project_slug,
        project_id,
        dataset_slug,
        dataset_id,
        int(number_text),
        UUID(hex=revision_hex),
    )
