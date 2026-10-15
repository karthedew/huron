"""Raw revision, release and staging layout constructors."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from huron.core.catalog.paths import dataset_dir
from huron.core.foundation.errors import PathRuleViolation
from huron.core.foundation.names import Slugged, validate_tag

if TYPE_CHECKING:
    from pathlib import PurePosixPath
    from uuid import UUID


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
