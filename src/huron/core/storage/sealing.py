"""tusd's files of an upload, and the seal that copies a complete upload into the object area.

tusd keeps an upload in ``.tus-uploads`` as three files: ``<id>`` holds the bytes, ``<id>.info``
holds the declared size, and ``<id>.lock`` exists while tusd works on the upload. A seal copies
the bytes into a new file in the object area of the organization. Each method here is one call
in the API's disk pool.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.storage.errors import StorageError
from huron.core.storage.layout import OBJECT_DIR_MODE, UPLOADS

if TYPE_CHECKING:
    from huron.core.storage.lakepath import LakePath
    from huron.core.storage.ports import SealedFile, Storage

__all__ = ["Completeness", "Inspection", "Sealer"]


class Completeness(StrEnum):
    """What tusd's files say about an upload.

    ``complete``: the API can seal the upload. ``no_info``: the ``.info`` file is missing or
    cannot be read. ``deferred``: the upload has no declared length. ``incomplete``: the data
    file is missing or shorter than the attempt, so tusd can still write to it. ``mismatched``:
    the ``.info`` file declares another size than the attempt, or the data file is larger than
    the attempt, so the upload can never become complete. ``locked``: tusd works on the upload.
    """

    COMPLETE = "complete"
    NO_INFO = "no_info"
    DEFERRED = "deferred"
    INCOMPLETE = "incomplete"
    MISMATCHED = "mismatched"
    LOCKED = "locked"


@dataclass(frozen=True, slots=True)
class Inspection:
    """What a check of tusd's files found; ``received`` is the size that disagrees with the
    attempt for ``mismatched``, else ``None``.
    """

    completeness: Completeness
    received: int | None = None


class Sealer:
    """Reads and removes tusd's files of an upload, and seals a complete upload."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def check(self, upload_id: uuid.UUID, size: int, *, locked: bool = True) -> Inspection:
        """Whether the upload ``upload_id`` of ``size`` bytes is complete on disk.

        An upload is complete when its ``.info`` file exists and declares ``size`` bytes with a
        length that is not deferred, and its data file holds exactly ``size`` bytes. With
        ``locked``, a ``.lock`` file makes the upload ``locked``: tusd still works on it.
        tusd's pre-finish hook checks without it, because tusd holds the lock during the hook.
        The check reads the files only. It sends no request to tusd. Raises ``StorageError``
        when ``.tus-uploads`` is not a directory: the caller tries again later.
        """
        self._require_uploads()
        info = _info(self._storage.read_bytes(_file(upload_id, ".info")))
        if info is None:
            return Inspection(Completeness.NO_INFO)
        if info.deferred:
            return Inspection(Completeness.DEFERRED)
        if info.size != size:
            return Inspection(Completeness.MISMATCHED, info.size)
        data = self._storage.stat(_file(upload_id))
        if data is None or data.kind != "file" or data.size < size:
            return Inspection(Completeness.INCOMPLETE)
        if data.size > size:
            return Inspection(Completeness.MISMATCHED, data.size)
        if locked and self._storage.stat(_file(upload_id, ".lock")) is not None:
            return Inspection(Completeness.LOCKED)
        return Inspection(Completeness.COMPLETE)

    def has_info(self, upload_id: uuid.UUID) -> bool:
        """Whether tusd made the ``.info`` file of ``upload_id``.

        Raises ``StorageError`` when ``.tus-uploads`` is not a directory, so that a lake that
        lost its upload directory never answers "no file".
        """
        self._require_uploads()
        return self._storage.stat(_file(upload_id, ".info")) is not None

    def seal(self, upload_id: uuid.UUID, destination: LakePath, size: int) -> SealedFile:
        """Copy the ``size`` bytes of the upload ``upload_id`` to the new object ``destination``.

        ``destination`` lies directly in an object area. A missing object area is made with
        mode ``0700``, and its organization directory is synced. A file at ``destination`` is
        removed first: a stop of the API during an earlier copy can leave a part of the copy
        there. Then :meth:`Storage.copy_sealed` makes, syncs and measures the copy. A missing
        ``.tus-uploads`` is a ``StorageError`` that the seal can retry.
        """
        area = destination.parent
        if self._storage.make_directory(area, OBJECT_DIR_MODE):
            self._storage.sync_directory(area.parent)
        self._storage.remove_file(destination)
        return self._storage.copy_sealed(_file(upload_id), destination, size)

    def upload_ids(self) -> set[uuid.UUID]:
        """The upload IDs that have a data file or a ``.info`` file in ``.tus-uploads``.

        A name that is not an upload ID in its canonical form, or the name of an entry that is
        not a file, gives no upload ID.
        """
        found: set[uuid.UUID] = set()
        for entry in self._storage.walk(UPLOADS):
            upload_id = _upload_id(entry.names[0].removesuffix(".info"))
            if len(entry.names) == 1 and entry.kind == "file" and upload_id is not None:
                found.add(upload_id)
        return found

    def remove_upload(self, upload_id: uuid.UUID) -> None:
        """Remove the data file and the ``.info`` file of ``upload_id``; a missing file is no
        error. A ``.lock`` file stays: tusd removes it, or the step before tusd starts.
        """
        self._storage.remove_file(_file(upload_id))
        self._storage.remove_file(_file(upload_id, ".info"))

    def _require_uploads(self) -> None:
        found = self._storage.stat(UPLOADS)
        if found is None or found.kind != "dir":
            raise StorageError(f"{UPLOADS} is not a directory", {"path": str(UPLOADS)})


@dataclass(frozen=True, slots=True)
class _Info:
    """The fields of a ``.info`` file that a seal needs."""

    size: int
    deferred: bool


def _file(upload_id: uuid.UUID, suffix: str = "") -> LakePath:
    return UPLOADS.joinpath(f"{upload_id}{suffix}")


def _info(data: bytes | None) -> _Info | None:
    """The size fields of a ``.info`` file; ``None`` when it is missing or malformed."""
    if data is None:
        return None
    try:
        document: Any = json.loads(data)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    size, deferred = document.get("Size"), document.get("SizeIsDeferred", False)
    if type(size) is not int or type(deferred) is not bool:
        return None
    return _Info(size, deferred)


def _upload_id(name: str) -> uuid.UUID | None:
    """The upload ID that ``name`` spells in its canonical form; ``None`` for another name."""
    try:
        parsed = uuid.UUID(name)
    except ValueError:
        return None
    return parsed if str(parsed) == name else None
