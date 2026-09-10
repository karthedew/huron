"""The sole constructor and parser for the POSIX layout shared by every layer.

Every path under the data root is built here and nowhere else, so the layout
is a fact of one module rather than a convention spread across callers. The
shape is a kind/value alternation rooted at the data root::

    organization/{slug}--{id}/project/{slug}--{id}/dataset/{slug}--{id}/
        raw/revision/{NNNNNN}--{id}     one committed raw revision
        {layer}/                        a layer's materialization
        gold/{slug}--{id}/              a single-source Gold product
        releases/{tag}.json             a release tag, beside raw, not in it
    organization/{...}/project/{...}/product/{slug}--{id}/   a fused product
    .staging/{ingest id}                an ingest session's envelope in progress

Each component carries both the slug, for people reading a listing, and the
id, for identity: slugs are unique among siblings and immutable, ids are
globally unique, and the ``--`` between them is unambiguous because a slug
may not contain ``--`` and an id is always 32 lower-case hexadecimal digits.

The module is also the only parser, and construction and parsing are
inverses: for any root, slugged entities, revision number and id that the
constructors accept, ``parse_revision_dir(root, revision_dir(root, ...))``
recovers exactly the slugs, ids, number and revision id that went in. Every
path is validated on construction, so a value that reaches the filesystem
has already passed the slug, tag, layer and range rules, and every rule
failure is a :class:`PathRuleViolation` with the shared code.
"""

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
_REVISION_COMPONENT = re.compile(r"^([0-9]{6})--([0-9a-f]{32})$")
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
    """Anything with an id and a slug: all a path constructor needs to know about an entity.

    Satisfied structurally by the catalog's frozen ``EntityRef`` and by the
    API's organization, project, dataset and product records alike, so a
    path can be built from whichever the caller holds. Read-only
    properties, not plain attributes: a path constructor only ever reads
    ``id``/``slug``, and a settable-attribute protocol would refuse a
    frozen dataclass, whose fields can never satisfy "settable".
    """

    @property
    def id(self) -> UUID:
        """The entity's identifier."""
        ...

    @property
    def slug(self) -> str:
        """The entity's URL- and path-safe name."""
        ...


class RevisionPath(NamedTuple):
    """The complete identity a revision directory encodes.

    What :func:`parse_revision_dir` recovers, and what :func:`revision_dir`
    consumed to build the directory in the first place.

    Attributes:
        org_slug: The organization's slug.
        org_id: The organization's id.
        project_slug: The project's slug.
        project_id: The project's id.
        dataset_slug: The dataset's slug.
        dataset_id: The dataset's id.
        revision_number: The revision's number, 1 to 999,999.
        revision_id: The revision's id.
    """

    org_slug: str
    org_id: UUID
    project_slug: str
    project_id: UUID
    dataset_slug: str
    dataset_id: UUID
    revision_number: int
    revision_id: UUID


def validate_slug(slug: str, max_len: int) -> None:
    """Refuse a slug that could not serve as the human half of a path component.

    A slug is 2 to ``max_len`` characters of lower-case ASCII letters,
    digits and single hyphens, starting with a letter or digit. A double
    hyphen is refused because ``--`` is the separator between a slug and
    its id in every path component, and keeping it out of slugs is what
    makes the component unambiguous to read back. A ``max_len`` below 2 is
    refused outright, since no slug could satisfy it.

    Args:
        slug: The candidate slug.
        max_len: The longest slug allowed here: ``ORG_PROJECT_SLUG_MAX`` or
            ``DATASET_SLUG_MAX``.

    Raises:
        PathRuleViolation: If ``slug`` breaks the pattern, contains ``--``
            or is longer than ``max_len``.
    """
    if max_len < 2 or not SLUG.fullmatch(slug) or "--" in slug or len(slug) > max_len:
        raise PathRuleViolation(f"invalid slug: {slug!r}")


def validate_org_slug(slug: str) -> None:
    """Refuse an organization slug that is malformed or shadows a top-level route.

    An organization's slug is the first segment of the browse URLs, so a
    slug equal to one of the application's own root routes (``admin``,
    ``api``, ``login``, ...) would make that organization unreachable or
    hijack the route; ``RESERVED_ROOT_SLUGS`` lists them. The general slug
    rule is applied first, through :func:`validate_slug`, and reports
    through the same exception.

    Args:
        slug: The candidate organization slug.

    Raises:
        PathRuleViolation: If ``slug`` is one of the reserved root slugs.
    """
    validate_slug(slug, ORG_PROJECT_SLUG_MAX)
    if slug in RESERVED_ROOT_SLUGS:
        raise PathRuleViolation(f"reserved organization slug: {slug!r}")


def validate_tag(tag: str) -> None:
    """Refuse a release tag that could not be a file name under ``releases/``.

    A tag is 2 to 63 characters of lower-case ASCII letters, digits, dots,
    underscores and hyphens, starting with a letter or digit; dots are
    allowed so version-shaped tags such as ``v1.2.0`` read naturally.

    Args:
        tag: The candidate release tag.

    Raises:
        PathRuleViolation: If ``tag`` does not match the tag pattern.
    """
    if not TAG.fullmatch(tag):
        raise PathRuleViolation(f"invalid release tag: {tag!r}")


def organization_dir(root: PurePosixPath, organization: Slugged) -> PurePosixPath:
    """Return an organization's directory: ``{root}/organization/{slug}--{id}``.

    The slug is validated as an organization slug on the way, so a reserved
    or malformed slug is refused as a :class:`PathRuleViolation` before any
    path is formed.

    Args:
        root: The data root every layout path descends from.
        organization: The organization's id and slug.

    Returns:
        The organization's directory under ``root``.
    """
    validate_org_slug(organization.slug)
    return root / "organization" / f"{organization.slug}--{organization.id.hex}"


def project_dir(root: PurePosixPath, organization: Slugged, project: Slugged) -> PurePosixPath:
    """Return a project's directory: ``{organization dir}/project/{slug}--{id}``.

    Both slugs are validated on the way; a failure is a
    :class:`PathRuleViolation`.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The project's id and slug.

    Returns:
        The project's directory under ``root``.
    """
    validate_slug(project.slug, ORG_PROJECT_SLUG_MAX)
    return organization_dir(root, organization) / "project" / f"{project.slug}--{project.id.hex}"


def dataset_dir(
    root: PurePosixPath, organization: Slugged, project: Slugged, dataset: Slugged
) -> PurePosixPath:
    """Return a dataset's directory: ``{project dir}/dataset/{slug}--{id}``.

    Every per-dataset path - layers, revisions, releases, single-source
    products - is a child of this directory. All three slugs are validated
    on the way; a failure is a :class:`PathRuleViolation`.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The owning project's id and slug.
        dataset: The dataset's id and slug.

    Returns:
        The dataset's directory under ``root``.
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
    """The per-layer segment under a dataset: ``dataset/{...}/{layer}``.

    ``layer`` accepts a plain string as well as a :class:`Layer` member so a
    value fresh off an API request can be validated and turned into a path in
    one step; :class:`Layer` stays the one place the four layer codes are
    spelled out, so this never drifts from ``pkg/catalog/layers.py``.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The owning project's id and slug.
        dataset: The dataset's id and slug.
        layer: The layer, as a member or as its lower-case code.

    Returns:
        The layer's directory under the dataset's.

    Raises:
        PathRuleViolation: If ``layer`` is a string that names no layer.
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
    """Return a raw revision's directory: ``{dataset dir}/raw/revision/{NNNNNN}--{id}``.

    A revision is a raw-layer notion, so its directory sits under the
    dataset's ``raw`` segment. The number is zero-padded to six digits so a
    plain directory listing sorts revisions in order, which bounds the
    number at 999,999. :func:`parse_revision_dir` inverts this function
    exactly.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The owning project's id and slug.
        dataset: The dataset's id and slug.
        number: The revision's number within the dataset, 1 to 999,999.
        revision_id: The revision's id.

    Returns:
        The revision's directory under ``root``.

    Raises:
        PathRuleViolation: If ``number`` is outside 1 to 999,999.
    """
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
    """Return a release tag's file: ``{dataset dir}/releases/{tag}.json``.

    ``releases`` is a sibling of ``raw``, not a child of it, so tagging a
    revision never writes inside a sealed revision directory, and sealing a
    revision never touches the tags. The tag is validated on the way; a
    failure is a :class:`PathRuleViolation`.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The owning project's id and slug.
        dataset: The dataset's id and slug.
        tag: The release tag.

    Returns:
        The tag file's path under ``root``.
    """
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

    The product slug is validated on the way, and so are the slugs of the
    entities it sits under; a failure is a :class:`PathRuleViolation`.

    Args:
        root: The data root every layout path descends from.
        organization: The owning organization's id and slug.
        project: The owning project's id and slug.
        product: The product's id and slug.
        dataset: The single dataset the product derives from, or None for a
            fused product that sits under the project.

    Returns:
        The product's directory under ``root``, whose ``repo/`` and
        ``iceberg/`` children hold its representations.
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
    """Return an ingest session's staging directory: ``{root}/.staging/{ingest id}``.

    Staging lives at the data root, beside ``organization/``, so a staged
    envelope and its final revision directory are on one filesystem; the
    rename that commits an envelope requires that. The dot prefix keeps it out of the
    organization listing.

    Args:
        root: The data root every layout path descends from.
        ingest_id: The ingest session the staging directory belongs to.

    Returns:
        The session's staging directory under ``root``.
    """
    return root / ".staging" / ingest_id.hex


class StagingPaths(NamedTuple):
    """The separate writable inputs, candidates and publishable envelope of one session.

    Attributes:
        root: Existing session root created only when ingestion begins.
        upload: Request-writable inputs, outside publication.
        completion: Private closed candidates, outside publication.
        envelope: Verified payload and immutable documents published by rename.
    """

    root: PurePosixPath
    upload: PurePosixPath
    completion: PurePosixPath
    envelope: PurePosixPath


def staging_paths(root: PurePosixPath, ingest_id: UUID) -> StagingPaths:
    """Return the fixed storage areas reserved for one upload session.

    Args:
        root: Data root owning the session.
        ingest_id: Reserved ingest identity.

    Returns:
        Distinct upload, completion and envelope paths beneath the session root.
    """
    session = staging_dir(root, ingest_id)
    return StagingPaths(session, session / "upload", session / "completion", session / "envelope")


def generation_file(entity_dir: PurePosixPath, generation: int) -> PurePosixPath:
    """Return the file holding one generation of an entity's descriptive record.

    Each update to an organization, project or dataset writes a new,
    numbered generation document under the entity's ``generations/``
    rather than rewriting one file, so every past state stays readable.
    The number is zero-padded to six digits so a listing sorts in order,
    which bounds it at 999,999.

    Args:
        entity_dir: The entity's directory, from :func:`organization_dir`,
            :func:`project_dir` or :func:`dataset_dir`.
        generation: The generation number, 1 to 999,999.

    Returns:
        ``{entity_dir}/generations/{NNNNNN}.json``.

    Raises:
        PathRuleViolation: If ``generation`` is outside 1 to 999,999.
    """
    if not 1 <= generation <= 999_999:
        raise PathRuleViolation(f"generation out of range: {generation}")
    return entity_dir / "generations" / f"{generation:06d}.json"


def _split(component: str, max_len: int) -> tuple[str, UUID]:
    """Split one ``{slug}--{id}`` path component back into its slug and id.

    The split is on the last ``--``: an id is 32 lower-case hexadecimal
    digits and can never contain the separator, so the last occurrence is
    the real boundary whatever the slug holds. The slug is then held to the
    same rule as on construction, so a component that would not have been
    built is not accepted when read either.

    Args:
        component: The directory name to split.
        max_len: The slug length limit for this kind of entity.

    Returns:
        The slug and the id.

    Raises:
        PathRuleViolation: If the component has no separator, its slug is
            invalid, or its id is not exactly 32 lower-case hexadecimal
            digits.
    """
    slug, separator, hex_id = component.rpartition("--")
    if not separator:
        raise PathRuleViolation(f"unparseable component: {component!r}")
    validate_slug(slug, max_len)
    if len(hex_id) != 32 or hex_id.lower() != hex_id or not re.fullmatch(r"[0-9a-f]{32}", hex_id):
        raise PathRuleViolation(f"invalid path UUID: {hex_id!r}")
    return slug, UUID(hex=hex_id)


def _validate_revision_layout(relative: PurePosixPath) -> None:
    """Refuse anything but the nine-segment raw revision layout.

    Args:
        relative: The candidate revision directory, relative to the data
            root.

    Raises:
        PathRuleViolation: If the segment count or any fixed-kind segment
            does not match
            ``organization/{X}/project/{Y}/dataset/{Z}/raw/revision/{W}``.
    """
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


def _parse_revision_component(component: str) -> tuple[int, UUID]:
    """Recover the revision number and id from the final ``{NNNNNN}--{hex}`` segment.

    Args:
        component: The last path segment of a revision directory.

    Returns:
        The revision number and the revision id the component encodes.

    Raises:
        PathRuleViolation: If ``component`` does not match the
            ``NNNNNN--hex`` shape or the number falls outside 1..999,999.
    """
    match = _REVISION_COMPONENT.fullmatch(component)
    if match is None:
        raise PathRuleViolation(f"invalid revision component: {component!r}")
    number = int(match.group(1))
    if number == 0:
        raise PathRuleViolation(f"invalid revision component: {component!r}")
    return number, UUID(hex=match.group(2))


def parse_revision_dir(root: PurePosixPath, path: PurePosixPath) -> RevisionPath:
    """Recover the complete identity tuple from an exact revision directory.

    The layout is ``organization/{X}/project/{Y}/dataset/{Z}/raw/revision/{NNNNNN--hex}``
    - nine segments, with the layer (``raw``) breaking what would otherwise be
    a clean kind/value alternation. Anything else, the old eight-segment
    layout included, is rejected rather than guessed at: a stale path left
    over from the earlier scheme must fail loudly, not resolve to the wrong
    dataset.

    This is the inverse of :func:`revision_dir`: for any arguments that
    function accepts, parsing what it built returns their slugs, ids, number
    and revision id unchanged. Every component is held to the construction
    rules, so a directory that could not have been built is refused rather
    than parsed.

    Args:
        root: The data root the path must lie under.
        path: The revision directory, exactly as :func:`revision_dir`
            returns it.

    Returns:
        The identity tuple the directory encodes.

    Raises:
        PathRuleViolation: If ``path`` is not under ``root``, does not have
            the nine-segment layout, or has a malformed slug, id, revision
            number or revision component.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PathRuleViolation(f"path is outside the data root: {path}") from exc
    _validate_revision_layout(relative)
    parts = relative.parts
    org_slug, org_id = _split(parts[1], ORG_PROJECT_SLUG_MAX)
    project_slug, project_id = _split(parts[3], ORG_PROJECT_SLUG_MAX)
    dataset_slug, dataset_id = _split(parts[5], DATASET_SLUG_MAX)
    revision_number, revision_id = _parse_revision_component(parts[8])
    return RevisionPath(
        org_slug,
        org_id,
        project_slug,
        project_id,
        dataset_slug,
        dataset_id,
        revision_number,
        revision_id,
    )
