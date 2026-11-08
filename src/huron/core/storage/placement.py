"""Placing a finished upload: measure it, link it into its collection, and undo a refused one.

tusd keeps a finished upload as ``.tus-uploads/<id>`` with its ``<id>.info`` beside it. The
API measures the file outside every lock, then, under its lock on the destination path, links it
to its destination and removes tusd's files. Each step here is one call in the API's disk pool.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.lake.uploads.errors import UploadSizeMismatch
from huron.core.storage.errors import SourceGone, StorageError
from huron.core.storage.layout import FILE_MODE, UPLOAD_DIR
from huron.schema.naming import BACKUP_SUFFIX, PART_SUFFIX

if TYPE_CHECKING:
    import uuid
    from pathlib import Path

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

    made_dirs: tuple[Path, ...]
    backup: Path | None


class CollectionDirectoryMissing(StorageError):
    """The collection directory of a placement does not exist; a placement never makes it."""

    def __init__(self, directory: Path) -> None:
        super().__init__(
            f"the collection directory {directory} does not exist."
            " To make the directory again, run huron adm repair for the collection",
            {"path": str(directory)},
        )


class Placer:
    """The disk steps of a placement on the lake at ``lake_path``."""

    def __init__(self, storage: Storage, lake_path: Path) -> None:
        self._storage = storage
        self._upload_dir = lake_path / UPLOAD_DIR

    def upload_file(self, upload_id: uuid.UUID) -> Path:
        """tusd's file of the upload's bytes."""
        return self._upload_dir / str(upload_id)

    def info_file(self, upload_id: uuid.UUID) -> Path:
        """tusd's description of the upload, beside its bytes."""
        return self._upload_dir / f"{upload_id}.info"

    def measure(self, upload_file: Path, size: int) -> Measured | None:
        """Measure a finished upload and make it readable as a placed file (mode ``0644``).

        The size and the inode come from the open descriptor, which the hash reads too. A size
        other than ``size`` raises ``UPLOAD_SIZE_MISMATCH`` before the hash. ``None`` when the
        file does not exist.
        """
        opened = self._storage.open_file(upload_file)
        if opened is None:
            return None
        with closing(opened):
            if opened.size != size:
                raise UploadSizeMismatch(size, opened.size)
            measured = _measured(opened)
            opened.set_mode(FILE_MODE)
            return measured

    def measure_destination(self, destination: Path, size: int) -> Measured | None:
        """Measure a file another attempt already placed; ``None`` unless it has ``size`` bytes."""
        opened = self._storage.open_file(destination)
        if opened is None:
            return None
        with closing(opened):
            return _measured(opened) if opened.size == size else None

    def backup_file(self, destination: Path, upload_id: uuid.UUID) -> Path:
        """The backup ``.<name>.<upload id>.huron-prev`` of the file an upload replaces."""
        return destination.with_name(f".{destination.name}.{upload_id}{BACKUP_SUFFIX}")

    def link(
        self,
        source: Path,
        info_file: Path,
        destination: Path,
        collection_dir: Path,
        upload_id: uuid.UUID,
    ) -> Linked:
        """Link ``source`` to ``destination`` inside ``collection_dir``, then remove tusd's files.

        The collection directory must exist. The directories between it and ``destination`` are
        made with :meth:`Storage.make_inheriting_dir`. An existing file is replaced through the
        part file ``.<name>.<upload id>.huron-part`` and keeps its bytes in the backup
        :meth:`backup_file` until the caller drops it. Raises :class:`CollectionDirectoryMissing`
        without the collection directory, and ``SourceGone``, after removing the directories it
        made, when ``source`` does not exist.
        """
        if not self._storage.is_directory(collection_dir):
            raise CollectionDirectoryMissing(collection_dir)
        made = tuple(
            directory
            for parent in reversed(destination.relative_to(collection_dir).parents[:-1])
            if self._storage.make_inheriting_dir(directory := collection_dir / parent)
        )
        part_name = f".{destination.name}.{upload_id}{PART_SUFFIX}"
        backup_name = self.backup_file(destination, upload_id).name
        try:
            backup = self._storage.link(source, destination, part_name, backup_name)
        except SourceGone:
            self._remove_empty(made)
            raise
        self._storage.remove_file(source)
        self._storage.remove_file(info_file)
        return Linked(made, backup)

    def drop_backup(self, destination: Path, upload_id: uuid.UUID) -> None:
        """Remove the backup of the file the upload replaced, once its receipt is recorded."""
        self._storage.remove_file(self.backup_file(destination, upload_id))

    def undo(self, destination: Path, inode: int, linked: Linked) -> None:
        """Take a placed file away again, but only while ``destination`` is still that inode.

        With a backup, the replaced file returns to ``destination``; without one, the placed
        file is removed. A backup of a destination that changed since is removed. Then the
        directories ``link`` made that are empty are removed, innermost first.
        """
        if self._storage.inode(destination) != inode:
            if linked.backup is not None:
                self._storage.remove_file(linked.backup)
        elif linked.backup is not None:
            self._storage.rename(linked.backup, destination)
        else:
            self._storage.remove_file(destination)
        self._remove_empty(linked.made_dirs)

    def _remove_empty(self, directories: tuple[Path, ...]) -> None:
        for directory in reversed(directories):
            if self._storage.is_directory(directory) and _empty(self._storage, directory):
                self._storage.remove_directory(directory)


def _measured(opened: OpenFile) -> Measured:
    return Measured(opened.size, opened.sha256(), opened.inode)


def _empty(storage: Storage, directory: Path) -> bool:
    return next(iter(storage.walk(directory)), None) is None
