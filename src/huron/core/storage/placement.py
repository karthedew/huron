"""Placing a finished upload: measure it, link it into its collection, and undo a refused one.

tusd keeps a finished upload as ``.tus-uploads/<id>`` with its ``<id>.info`` beside it. The
API measures the file outside every lock, then, under its lock on the destination path, links it
to its destination and removes tusd's files. Each step here is one call in the API's disk pool.
"""

from __future__ import annotations

from contextlib import closing, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.lake.uploads.errors import UploadSizeMismatch
from huron.core.storage.errors import StorageError
from huron.core.storage.layout import FILE_MODE, UPLOADS
from huron.core.storage.removal import prune
from huron.schema.naming import BACKUP_SUFFIX, PART_SUFFIX

if TYPE_CHECKING:
    import uuid

    from huron.core.storage.lakepath import LakePath
    from huron.core.storage.ports import OpenFile, Storage

__all__ = ["CollectionDirectoryMissing", "Linked", "Measured", "Placer"]


@dataclass(frozen=True, slots=True)
class Measured:
    """The receipt of a file: its size, its sha256 and its inode, all from one descriptor."""

    size: int
    sha256: str
    inode: int


@dataclass(frozen=True, slots=True)
class Linked:
    """A file linked to its destination.

    ``made_dirs`` are the directories made for it, outermost first. ``backup`` keeps the bytes
    of the file it replaced, ``None`` when the name was new.
    """

    made_dirs: tuple[LakePath, ...]
    backup: LakePath | None


class CollectionDirectoryMissing(StorageError):
    """The collection directory of a placement does not exist; a placement never makes it."""

    def __init__(self, directory: LakePath) -> None:
        super().__init__(
            f"the collection directory {directory} does not exist."
            " To make the directory again, run huron adm repair for the collection",
            {"path": str(directory)},
        )


class Placer:
    """The disk steps of a placement on the lake."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def measure(self, upload_id: uuid.UUID, size: int) -> Measured | None:
        """Measure a finished upload and make it readable as a placed file (mode ``0644``).

        The size and the inode come from the open descriptor, which the hash reads too. A size
        other than ``size`` raises ``UPLOAD_SIZE_MISMATCH`` before the hash. ``None`` when the
        file does not exist.
        """
        opened = self._storage.open_file(_upload_file(upload_id))
        if opened is None:
            return None
        with closing(opened):
            if opened.size != size:
                raise UploadSizeMismatch(size, opened.size)
            measured = _measured(opened)
            opened.set_mode(FILE_MODE)
            return measured

    def measure_destination(self, target: LakePath, size: int) -> Measured | None:
        """Measure a file another attempt already placed; ``None`` unless it has ``size`` bytes."""
        opened = self._storage.open_file(target)
        if opened is None:
            return None
        with closing(opened):
            return _measured(opened) if opened.size == size else None

    def link(
        self, upload_id: uuid.UUID, collection: LakePath, target: LakePath, inode: int
    ) -> Linked:
        """Link the upload's file to ``target`` inside ``collection``, then remove tusd's files.

        The collection directory must exist. The directories between it and ``target`` are
        made with :meth:`Storage.make_inheriting_dir`. The upload's file must still be a regular
        file with the measured ``inode``. An existing file is replaced through the part file
        ``.<name>.<upload id>.huron-part`` and keeps its bytes in the backup
        ``.<name>.<upload id>.huron-prev`` until :meth:`drop_backup`. Raises
        :class:`CollectionDirectoryMissing` without the collection directory, and
        ``ValueError`` for a ``target`` that is not below ``collection``. When a directory or
        the link fails, the empty directories that this call made are removed before the error
        goes on:
        ``SourceGone`` when the upload's file is gone or replaced, ``SymlinkInLake`` for a link
        at the upload's file or on the way to the target, and ``StorageError`` for any other
        failure, a missing ``.tus-uploads`` included.
        """
        depth = len(collection.names)
        if len(target.names) <= depth or target.names[:depth] != collection.names:
            raise ValueError(f"{target} is not below the collection directory {collection}")
        found = self._storage.stat(collection)
        if found is None:
            raise CollectionDirectoryMissing(collection)
        if found.kind != "dir":
            raise StorageError(f"{collection} is not a directory", {"path": str(collection)})
        made: list[LakePath] = []
        try:
            for size in range(depth + 1, len(target.names)):
                directory = collection.joinpath(*target.names[depth:size])
                if self._storage.make_inheriting_dir(directory):
                    made.append(directory)
            backup = self._storage.link(
                _upload_file(upload_id),
                target,
                inode=inode,
                part_name=f".{target.name}.{upload_id}{PART_SUFFIX}",
                backup_name=_backup_name(target, upload_id),
            )
        except Exception:
            with suppress(StorageError):
                prune(self._storage, made)
            raise
        self._storage.remove_file(_upload_file(upload_id))
        self._storage.remove_file(UPLOADS.joinpath(f"{upload_id}.info"))
        return Linked(tuple(made), backup)

    def drop_backup(self, target: LakePath, upload_id: uuid.UUID) -> None:
        """Remove the backup of the file the upload replaced, once its receipt is recorded."""
        self._storage.remove_file(target.parent.joinpath(_backup_name(target, upload_id)))

    def undo(self, target: LakePath, inode: int, linked: Linked) -> None:
        """Take a placed file away again, but only while ``target`` is still that inode.

        With a backup, the replaced file returns to ``target``; without one, the placed file is
        removed. A backup of a target that changed since is removed. Then the directories
        ``link`` made that are empty are removed, innermost first.
        """
        if linked.backup is None:
            self._storage.remove_file(target, inode=inode)
        else:
            found = self._storage.stat(target)
            if found is not None and found.inode == inode:
                self._storage.rename(linked.backup, target)
            else:
                self._storage.remove_file(linked.backup)
        prune(self._storage, linked.made_dirs)


def _upload_file(upload_id: uuid.UUID) -> LakePath:
    return UPLOADS.joinpath(str(upload_id))


def _backup_name(target: LakePath, upload_id: uuid.UUID) -> str:
    return f".{target.name}.{upload_id}{BACKUP_SUFFIX}"


def _measured(opened: OpenFile) -> Measured:
    return Measured(opened.size, opened.sha256(), opened.inode)
