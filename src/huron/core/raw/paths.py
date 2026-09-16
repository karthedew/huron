"""Raw revision, release and staging layout constructors and parsing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from huron.core.catalog.paths import dataset_dir
from huron.core.foundation.errors import PathRuleViolation
from huron.core.foundation.names import (
    DATASET_SLUG_MAX,
    ORG_PROJECT_SLUG_MAX,
    Slugged,
    split_component,
    validate_tag,
)

if TYPE_CHECKING:
    from pathlib import PurePosixPath

_REVISION_COMPONENT = re.compile(r"^([0-9]{6})--([0-9a-f]{32})$")


class RevisionPath(NamedTuple):
    """The complete hierarchy and revision identity encoded in a revision directory."""

    org_slug: str
    org_id: UUID
    project_slug: str
    project_id: UUID
    dataset_slug: str
    dataset_id: UUID
    revision_number: int
    revision_id: UUID


class StagingPaths(NamedTuple):
    """Distinct writable inputs, completion candidates and publishable envelope."""

    root: PurePosixPath
    upload: PurePosixPath
    completion: PurePosixPath
    envelope: PurePosixPath


def revision_dir(
    root: PurePosixPath,
    organization: Slugged,
    project: Slugged,
    dataset: Slugged,
    number: int,
    revision_id: UUID,
) -> PurePosixPath:
    """Build the exact immutable Raw revision directory.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Owning project.
        dataset: Owning dataset.
        number: Revision number from 1 through 999,999.
        revision_id: Reserved revision identity.

    Returns:
        The revision directory.

    Raises:
        PathRuleViolation: If the revision number is outside the representable range.
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
    root: PurePosixPath, organization: Slugged, project: Slugged, dataset: Slugged, tag: str
) -> PurePosixPath:
    """Build a dataset-level release tag path beside Raw, outside sealed revisions.

    Args:
        root: Data root.
        organization: Owning organization.
        project: Owning project.
        dataset: Owning dataset.
        tag: Immutable tag name.

    Returns:
        The release JSON path.
    """
    validate_tag(tag)
    return dataset_dir(root, organization, project, dataset) / "releases" / f"{tag}.json"


def staging_dir(root: PurePosixPath, ingest_id: UUID) -> PurePosixPath:
    """Build an upload's private staging root.

    Args:
        root: Data root.
        ingest_id: Upload identity.

    Returns:
        The staging root on the publication filesystem.
    """
    return root / ".staging" / ingest_id.hex


def staging_paths(root: PurePosixPath, ingest_id: UUID) -> StagingPaths:
    """Build the fixed isolated storage areas of one upload.

    Args:
        root: Data root.
        ingest_id: Upload identity.

    Returns:
        Distinct upload, candidate and envelope directories.
    """
    session = staging_dir(root, ingest_id)
    return StagingPaths(session, session / "upload", session / "completion", session / "envelope")


def _validate_revision_layout(relative: PurePosixPath) -> None:
    """Check the exact nine-segment Raw layout.

    Args:
        relative: Candidate path relative to the data root.

    Raises:
        PathRuleViolation: If the layout differs from the supported revision layout.
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
    """Decode a six-digit revision number and lower-case hexadecimal UUID.

    Args:
        component: Final revision directory component.

    Returns:
        The revision number and identity.

    Raises:
        PathRuleViolation: If the encoding or number is invalid.
    """
    match = _REVISION_COMPONENT.fullmatch(component)
    if match is None:
        raise PathRuleViolation(f"invalid revision component: {component!r}")
    number = int(match.group(1))
    if number == 0:
        raise PathRuleViolation(f"invalid revision component: {component!r}")
    return number, UUID(hex=match.group(2))


def parse_revision_dir(root: PurePosixPath, path: PurePosixPath) -> RevisionPath:
    """Recover exact hierarchy and revision identities, refusing alternate layouts.

    Args:
        root: Data root.
        path: Exact revision directory.

    Returns:
        The decoded hierarchy and revision identities.

    Raises:
        PathRuleViolation: If the path escapes the root.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PathRuleViolation(f"path is outside the data root: {path}") from exc
    _validate_revision_layout(relative)
    parts = relative.parts
    org_slug, org_id = split_component(parts[1], ORG_PROJECT_SLUG_MAX)
    project_slug, project_id = split_component(parts[3], ORG_PROJECT_SLUG_MAX)
    dataset_slug, dataset_id = split_component(parts[5], DATASET_SLUG_MAX)
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
