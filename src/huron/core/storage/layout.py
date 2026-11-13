"""Where things live on the lake, and the modes they have."""

from __future__ import annotations

from dataclasses import dataclass

from huron.core.storage.lakepath import LakePath
from huron.schema.naming import (
    METADATA_FILE,
    NFS_PREFIX,
    PART_SUFFIX,
    SNAPSHOT_DIR,
    NamingError,
)

__all__ = [
    "DIRECTORY_MODE",
    "FILE_MODE",
    "LINK_PROBE_PREFIX",
    "MARKER_FILE",
    "NFS_PREFIX",
    "OBJECT_DIR",
    "OBJECT_DIR_MODE",
    "ORGANIZATION_MODE",
    "SNAPSHOT_DIR",
    "UNWALKED",
    "UPLOADS",
    "UPLOAD_DIR",
    "UPLOAD_DIR_MODE",
    "OrganizationPlace",
    "is_ignored_entry",
    "is_reserved_entry",
]

MARKER_FILE = ".huron"
#: tusd's filestore directory, directly below the lake path.
UPLOAD_DIR = ".tus-uploads"
#: tusd's filestore on the lake.
UPLOADS = LakePath.of(UPLOAD_DIR)
#: The private area of sealed objects, directly in each organization directory. A publication
#: links an object from it, and a hard link works only inside one mount.
OBJECT_DIR = ".huron-objects"
#: The start of the name of a readiness probe's file, in an object area and its organization
#: directory. A probe that stops before its end leaves the file.
LINK_PROBE_PREFIX = f"{MARKER_FILE}-link-probe-"
#: The directories that every walk yields but never enters. The path rules refuse both names
#: in a collection, so no recorded file is below one of them.
UNWALKED = frozenset({OBJECT_DIR, SNAPSHOT_DIR})

#: Everyone may traverse an organization directory; nobody but its owner and group may list it.
ORGANIZATION_MODE = 0o2751
#: Catalog, namespace, collection and intermediate directories: the group reads, setgid passes
#: the catalog's group down to every directory made below it.
DIRECTORY_MODE = 0o2750
#: A published file and ``metadata.json``: readable by whoever may traverse the directories above.
FILE_MODE = 0o644
#: tusd's filestore: only the service user.
UPLOAD_DIR_MODE = 0o700
#: The object area: only the service user, so an object is private until a publication links it.
OBJECT_DIR_MODE = 0o700


@dataclass(frozen=True, slots=True)
class OrganizationPlace:
    """Where an organization's directory is on the lake, and which marker guards it.

    ``base`` is the lake path of the organization's root; the organization's directory is
    always ``base / name``, and every API path of it (``<organization>/<catalog>/…``) lies
    below ``base``. With ``own_marker`` the organization's directory carries its own marker;
    otherwise the marker at ``base`` guards it.
    """

    name: str
    base: LakePath
    own_marker: bool

    @property
    def directory(self) -> LakePath:
        """The organization's directory."""
        return self.base.joinpath(self.name)

    @property
    def objects(self) -> LakePath:
        """The organization's object area, inside its directory and its mount."""
        return self.directory.joinpath(OBJECT_DIR)

    @property
    def marker_directory(self) -> LakePath:
        """The directory whose ``.huron`` marker guards the organization."""
        return self.directory if self.own_marker else self.base

    def locate(self, api_path: str) -> LakePath:
        """The lake path of an API path of this organization (``<name>/…``).

        Raises ``NAME_INVALID`` for a path of another organization or with a name that
        breaks the rule ``lake_name``.
        """
        relative = LakePath.parse(api_path)
        if relative.names[0] != self.name:
            raise NamingError("lake_name", api_path)
        return self.base.joinpath(*relative.names)

    def mode_of(self, location: LakePath) -> int:
        """The mode of a directory at or below the organization's directory."""
        below = location.relative_to(self.directory)
        return DIRECTORY_MODE if below else ORGANIZATION_MODE


def is_reserved_entry(rel_path: str) -> bool:
    """Whether an entry inside a collection belongs to Huron rather than to the user."""
    name = rel_path.rpartition("/")[2]
    return rel_path == METADATA_FILE or name.startswith(MARKER_FILE) or name.endswith(PART_SUFFIX)


def is_ignored_entry(rel_path: str) -> bool:
    """Whether a file inside a collection is one that no commit records: Huron's own, or a
    ``.nfs*`` file, which an NFS client keeps for a removed file that a process holds open.

    The path rules refuse each of these names (:func:`~huron.schema.naming.check_rel_path`).
    """
    return is_reserved_entry(rel_path) or rel_path.rpartition("/")[2].startswith(NFS_PREFIX)
