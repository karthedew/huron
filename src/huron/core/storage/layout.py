"""Where things live on the lake, and the modes they have."""

from __future__ import annotations

from dataclasses import dataclass

from huron.core.storage.lakepath import LakePath
from huron.schema.naming import BACKUP_SUFFIX, METADATA_FILE, PART_SUFFIX, NamingError

__all__ = [
    "DIRECTORY_MODE",
    "FILE_MODE",
    "MARKER_FILE",
    "ORGANIZATION_MODE",
    "UPLOADS",
    "UPLOAD_DIR",
    "UPLOAD_DIR_MODE",
    "OrganizationPlace",
    "is_reserved_entry",
]

MARKER_FILE = ".huron"
#: tusd's filestore directory, directly below the lake path.
UPLOAD_DIR = ".tus-uploads"
#: tusd's filestore on the lake.
UPLOADS = LakePath.of(UPLOAD_DIR)

#: Everyone may traverse an organization directory; nobody but its owner and group may list it.
ORGANIZATION_MODE = 0o2751
#: Catalog, namespace, collection and intermediate directories: the group reads, setgid passes
#: the catalog's group down to every directory made below it.
DIRECTORY_MODE = 0o2750
#: A placed file and ``metadata.json``: readable by whoever may traverse the directories above.
FILE_MODE = 0o644
#: tusd's filestore: only the service user.
UPLOAD_DIR_MODE = 0o700


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
    return (
        rel_path == METADATA_FILE
        or name.startswith(MARKER_FILE)
        or name.endswith((PART_SUFFIX, BACKUP_SUFFIX))
    )
