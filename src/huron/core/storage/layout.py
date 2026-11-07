"""Where things live on the share."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from huron.core.storage.errors import StorageError
from huron.schema.naming import METADATA_FILE, PART_SUFFIX

__all__ = [
    "DIRECTORY_MODE",
    "FILE_MODE",
    "MARKER_FILE",
    "ORGANIZATION_MODE",
    "UPLOAD_DIR",
    "UPLOAD_DIR_MODE",
    "DirectoryKind",
    "OrganizationPlace",
    "is_reserved_entry",
    "mode_of",
    "place_of",
    "resolve",
]

MARKER_FILE = ".huron"
#: tusd's filestore directory, directly below the lake path.
UPLOAD_DIR = ".tus-uploads"

#: Everyone may traverse an organization directory; nobody but its owner and group may list it.
ORGANIZATION_MODE = 0o2751
#: Catalog, namespace, collection and intermediate directories: the group reads, setgid passes
#: the catalog's group down to every directory made below it.
DIRECTORY_MODE = 0o2750
#: A placed file and ``metadata.json``: readable by whoever may traverse the directories above.
FILE_MODE = 0o644
#: tusd's filestore: only the service user.
UPLOAD_DIR_MODE = 0o700


class DirectoryKind(StrEnum):
    """The kinds of directory Huron creates."""

    ORGANIZATION = "organization"
    CATALOG = "catalog"
    NAMESPACE = "namespace"
    NAMESPACE_WITH_COLLECTIONS = "namespace_with_collections"
    COLLECTION = "collection"


def mode_of(kind: DirectoryKind) -> int:
    """The mode a directory of ``kind`` has on the share."""
    return ORGANIZATION_MODE if kind is DirectoryKind.ORGANIZATION else DIRECTORY_MODE


def resolve(prefix: Path, relative: str) -> Path:
    """``prefix / relative`` for a path the API returned; refuses anything escaping the prefix."""
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageError("the path is outside the share", {"path": relative})
    return prefix.joinpath(*parts)


@dataclass(frozen=True, slots=True)
class OrganizationPlace:
    """Where an organization's directory is on this machine, and which marker guards it.

    ``base`` is the organization's configured root, or the CLI's mount prefix when it has none;
    the organization's directory is always ``base / name``, and every path the API returns for
    it (``<organization>/<catalog>/…``) lies below ``base``. An organization with a root, or any
    declared one, carries its own marker in its directory; the others share the marker at the
    mount prefix.
    """

    name: str
    base: Path
    rooted: bool
    declared: bool = False
    export: str | None = None

    @property
    def directory(self) -> Path:
        """The organization's directory."""
        return self.base / self.name

    @property
    def own_marker(self) -> bool:
        """Whether the organization's directory carries its own marker."""
        return self.rooted or self.declared

    @property
    def marker_directory(self) -> Path:
        """The directory whose ``.huron`` marker guards the organization."""
        return self.directory if self.own_marker else self.base

    def resolve(self, relative: str) -> Path:
        """The absolute path of an API path below this organization (``<name>/…``)."""
        if relative.split("/")[0] != self.name:
            raise StorageError(
                f"{relative} is not in organization {self.name}",
                {"path": relative, "organization": self.name},
            )
        return resolve(self.base, relative)


def place_of(
    name: str, root: str | None, declared: bool, prefix: Path, export: str | None = None
) -> OrganizationPlace:
    """The place of organization ``name``: below ``root`` when it has one, else below ``prefix``.

    ``root`` must be an absolute, normalized path; anything else is refused. ``export`` is the
    NFS source the root is mounted from, for hints only.
    """
    if root is None:
        return OrganizationPlace(name, prefix, rooted=False, declared=declared, export=export)
    path = PurePosixPath(root)
    if not path.is_absolute() or str(path) != (root.rstrip("/") or "/") or ".." in path.parts:
        raise StorageError(
            f"the root {root!r} of organization {name} is not an absolute, normalized path",
            {"organization": name, "root": root},
        )
    return OrganizationPlace(name, Path(root), rooted=True, declared=declared, export=export)


def is_reserved_entry(rel_path: str) -> bool:
    """Whether an entry inside a collection belongs to Huron rather than to the user."""
    name = PurePosixPath(rel_path).name
    return rel_path == METADATA_FILE or name.startswith(MARKER_FILE) or name.endswith(PART_SUFFIX)
