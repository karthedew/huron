"""The directories of the lake: make them, give a catalog its group, write ``metadata.json``
and remove them.

Below a catalog directory a new directory gets its setgid bit and its group only from the
filesystem's inheritance. ``chmod`` by a caller outside a directory's group clears the setgid
bit without an error, so nothing here calls ``chmod`` on a directory below a catalog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from huron.core.storage.errors import StorageError
from huron.core.storage.layout import FILE_MODE, ORGANIZATION_MODE, UNWALKED
from huron.core.storage.ports import Outcome
from huron.schema.naming import METADATA_FILE, PART_SUFFIX

if TYPE_CHECKING:
    from huron.core.storage.lakepath import LakePath
    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.ports import Entry, GroupResult, Storage

__all__ = ["DirectoryWriter"]

_log = structlog.get_logger(__name__)


class DirectoryWriter:
    """Makes and removes the directories of organizations, catalogs, namespaces and
    collections, gives catalog directories their group and writes ``metadata.json``.

    ``service_gid`` is the service group, which a catalog without a share group carries.
    """

    def __init__(self, storage: Storage, service_gid: int) -> None:
        self._storage = storage
        self._service_gid = service_gid

    def make(self, place: OrganizationPlace, location: LakePath) -> bool:
        """Make the directory at ``location`` of ``place``; ``False`` when an empty one is adopted.

        The organization's own directory gets its mode ``2751``. Any other directory lies below
        a catalog and gets ``0750`` with the setgid bit and the group of its parent from the
        filesystem, else ``InheritanceFailed``. An existing empty directory is adopted as it is.
        Any other entry at ``location`` is refused: a link with ``SYMLINK_IN_LAKE``, anything
        else with ``STORAGE_FAILED``.
        """
        found = self._storage.stat(location)
        if found is not None:
            if found.kind == "dir" and self._storage.is_empty(location):
                return False
            raise StorageError(
                f"{location} exists and is not an empty directory", {"path": str(location)}
            )
        if place.mode_of(location) == ORGANIZATION_MODE:
            return self._storage.make_directory(location, ORGANIZATION_MODE)
        return self._storage.make_inheriting_dir(location)

    def group_for(self, share_group: str | None) -> str | int:
        """The group a catalog directory carries: its share group, else the service gid."""
        return self._service_gid if share_group is None else share_group

    def set_group(self, location: LakePath, share_group: str | None) -> GroupResult:
        """Try to give the catalog directory at ``location`` the group of :meth:`group_for`.

        A refusal, or a name that this machine cannot resolve, is ``PENDING``.
        """
        return self._storage.set_group(location, self.group_for(share_group))

    def write_metadata(self, location: LakePath, body: bytes) -> bool:
        """Write ``body`` atomically as the ``metadata.json`` of the directory ``location``.

        The file gets the mode ``0644``. Equal bytes are not written again. Returns whether the
        file was written.
        """
        metadata = location.joinpath(METADATA_FILE)
        if self._storage.read_bytes(metadata) == body:
            return False
        self._storage.write_bytes(metadata, body, FILE_MODE)
        return True

    def remove(self, location: LakePath) -> Outcome:
        """Remove an empty directory; one that is not empty stays (``KEPT``)."""
        return self._storage.remove_directory(location)

    def remove_collection(self, location: LakePath) -> Outcome:
        """Remove what Huron put into a collection directory, then the directory.

        A collection without recorded files holds no published file. This removes
        ``metadata.json``, part files and the subdirectories that are then empty, the deepest
        entries first. A symbolic link below is not removed and keeps the directories above it,
        with the log event ``disk.link_found``. The walk does not enter a ``.snapshot`` or
        ``.huron-objects`` directory, and this removes neither of them: the path rules refuse
        both names in a collection, so Huron puts no file in them. The directory stays
        (``KEPT``) while any entry is in it. A missing directory is ``MISSING``.
        """
        if self._storage.stat(location) is None:
            return Outcome.MISSING
        entries = sorted(self._storage.walk(location), key=_depth, reverse=True)
        for entry in entries:
            found = location.joinpath(*entry.names)
            if entry.kind == "dir" and entry.names[-1] not in UNWALKED:
                self._storage.remove_directory(found)
            elif entry.kind == "symlink":
                _log.warning("disk.link_found", path=str(found))
            elif entry.kind == "file" and _belongs_to_huron(entry):
                self._storage.remove_file(found)
        return self._storage.remove_directory(location)


def _depth(entry: Entry) -> int:
    return len(entry.names)


def _belongs_to_huron(entry: Entry) -> bool:
    return entry.names == (METADATA_FILE,) or entry.names[-1].endswith(PART_SUFFIX)
