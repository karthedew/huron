"""Publication on the lake: the filesystem steps of a commit request, and the link probe.

The API publishes an accepted request one entry at a time: it turns each entry into a step and
gives the step to :meth:`Publisher.apply`. A step compares its place with the state before the
step and with the state after it:

- The state after: the step is done. Its directory is synced again, as a crash can come before
  the first sync.
- The state before: the step makes its change, then syncs the directory.
- Any other state: the step is blocked, and nothing changes. Huron never changes an entry that
  the request does not expect.

Thus a step can run again after a failure at any point. A file is identified by its inode. The
sealed object keeps the new inode in the object area, so no other file can get that number
meanwhile. An old file that has its own object in the object area keeps its inode in the same
way until the request is final. The inode number of an old file without such an object can go
to another file once that old file is removed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError, SymlinkInLake
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import FILE_MODE, LINK_PROBE_PREFIX, OBJECT_DIR, OBJECT_DIR_MODE
from huron.core.storage.ports import Outcome
from huron.schema.naming import PART_SUFFIX

if TYPE_CHECKING:
    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.ports import Stat, Storage


__all__ = [
    "AddFile",
    "BlockReason",
    "MakeDirectory",
    "PruneDirectory",
    "Publisher",
    "RemoveDirectory",
    "RemoveFile",
    "Step",
    "StepOutcome",
    "StepResult",
]


class StepOutcome(StrEnum):
    """What a step did.

    ``done``: the place has the state after the step. ``kept``: a prune kept a directory that
    holds an entry, and the step is done. ``blocked``: the place has an unexpected state, and
    an operator must look at it.
    """

    DONE = "done"
    KEPT = "kept"
    BLOCKED = "blocked"


class BlockReason(StrEnum):
    """Why a step is blocked.

    ``inode_unknown`` comes from the caller, not from :meth:`Publisher.apply`: a removal of a
    file whose inode Huron never learned cannot tell that file from another file, so the caller
    makes no step for it.
    """

    FOREIGN_ENTRY = "foreign_entry"
    DIRECTORY_MISSING = "directory_missing"
    DIRECTORY_NOT_EMPTY = "directory_not_empty"
    OBJECT_MISSING = "object_missing"
    SYMBOLIC_LINK = "symbolic_link"
    INODE_UNKNOWN = "inode_unknown"


@dataclass(frozen=True, slots=True)
class StepResult:
    """The result of a step; a blocked step has its ``reason`` and the ``path`` that blocks."""

    outcome: StepOutcome
    reason: BlockReason | None = None
    path: LakePath | None = None

    @classmethod
    def blocked(cls, reason: BlockReason, path: LakePath) -> StepResult:
        """The result of a step that ``path`` blocks for ``reason``."""
        return cls(StepOutcome.BLOCKED, reason, path)

    @property
    def done(self) -> bool:
        """Whether the step is done: ``done`` or ``kept``."""
        return self.outcome is not StepOutcome.BLOCKED

    @property
    def detail(self) -> str:
        """A sentence about a blocked step for the operator; empty for a done step."""
        if self.reason is None:
            return ""
        return _DETAILS[self.reason].format(path=self.path)


@dataclass(frozen=True, slots=True)
class AddFile:
    """Link the sealed object ``source`` to ``target``, in place of the file there.

    ``source`` lies directly in the object area of an organization, and ``target`` lies below
    the same organization directory, outside the object area. ``new_inode`` is the inode of the
    object from its seal. ``old_inode`` is the inode of the file at ``target`` before the step,
    ``None`` for a new path. The temporary name holds ``upload_id``, so it is unique.
    """

    source: LakePath
    target: LakePath
    new_inode: int
    old_inode: int | None
    upload_id: uuid.UUID

    def __post_init__(self) -> None:
        area = self.source.parent
        if (
            area.name != OBJECT_DIR
            or not _below(self.target, area.parent)
            or _below(self.target, area)
        ):
            raise ValueError(f"{self.source} and {self.target} are not in one organization")

    @property
    def temporary(self) -> LakePath:
        """The name beside ``target`` that the object is linked to before the rename."""
        name = f".{self.target.name}.{self.upload_id}{PART_SUFFIX}"
        return self.target.parent.joinpath(name)


@dataclass(frozen=True, slots=True)
class RemoveFile:
    """Remove the file at ``target``, which has the inode ``old_inode`` before the step."""

    target: LakePath
    old_inode: int


@dataclass(frozen=True, slots=True)
class MakeDirectory:
    """Make the directory ``location``; it inherits the setgid bit and the group."""

    location: LakePath


@dataclass(frozen=True, slots=True)
class RemoveDirectory:
    """Remove the empty directory ``location``, to free its path for an added file."""

    location: LakePath


@dataclass(frozen=True, slots=True)
class PruneDirectory:
    """Remove the directory ``location`` that the request made empty; keep it when it is not."""

    location: LakePath


type Step = AddFile | RemoveFile | MakeDirectory | RemoveDirectory | PruneDirectory


class Publisher:
    """Applies the steps of a publication through the one ``Storage`` port.

    The publisher makes no symbolic link, and it never opens a file for a write.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def apply(self, step: Step) -> StepResult:
        """Apply ``step`` and sync the directory that it changes.

        - ``AddFile``: link the object to the temporary name, sync, rename it over the target,
          sync. A target that is a directory, or another file, blocks. A missing object blocks.
        - ``RemoveFile``: unlink, sync. Another file at the target blocks.
        - ``MakeDirectory``: make the directory, sync. A file at the place blocks.
        - ``RemoveDirectory``: remove the empty directory, sync. A directory that holds an
          entry blocks, and the entry stays.
        - ``PruneDirectory``: as ``RemoveDirectory``, but a directory that holds an entry stays,
          and the step is done (``kept``).

        A symbolic link at any name of the way blocks. A name on the way that is not a
        directory blocks an add or a new directory (``foreign_entry``), and so does a missing
        directory on the way (``directory_missing``). The result names that name. For a
        removal, a broken way means that the name to remove is gone: the step is done, with no
        sync, because no directory holds the name any more. Any other storage failure
        (``ENOSPC``, ``EIO``, a failed sync, a refused permission) raises ``StorageError``: the
        step is not done, and it can run again.
        """
        try:
            return self._checked(step)
        except SymlinkInLake as error:
            return StepResult.blocked(
                BlockReason.SYMBOLIC_LINK, LakePath.parse(str(error.context["path"]))
            )

    def probe(self, place: OrganizationPlace) -> None:
        """Make a real hard link from the object area of ``place`` into its directory, then
        remove it.

        Two names with the same device number can still be on two mounts, so only a real link
        shows that publication can link. The steps:

        1. Make the object area with mode ``0700`` when it is missing, and sync the organization
           directory after the create. An object area that another probe made meanwhile is
           kept.
        2. Give the object area the mode ``0700`` when it has another mode.
        3. Write a probe file with a name that is unique for this call, link it into the
           organization directory with :meth:`Storage.link_once`, and remove the link and the
           file. The file is removed also when the link fails.

        The probe lists no directory and changes no other entry, so two probes can overlap.
        A probe file that a stopped probe leaves stays in place under its reserved name, for
        the drift check to report. Raises ``StorageError`` when a step fails, ``EXDEV`` when
        the object area is on another mount.
        """
        area = place.objects
        if self._storage.make_directory(area, OBJECT_DIR_MODE):
            self._storage.sync_directory(place.directory)
        self._storage.set_mode(area, OBJECT_DIR_MODE)
        name = f"{LINK_PROBE_PREFIX}{uuid.uuid4().hex}"
        source, link = area.joinpath(name), place.directory.joinpath(name)
        self._storage.write_bytes(source, b"", FILE_MODE)
        try:
            self._storage.link_once(source, link)
            self._storage.remove_file(link)
        finally:
            self._storage.remove_file(source)

    def _checked(self, step: Step) -> StepResult:
        """Apply ``step``; a failure on a broken way gives the result of :meth:`_broken_way`."""
        try:
            return self._run(step)
        except SymlinkInLake:
            raise
        except StorageError:
            broken = self._broken_way(step)
            if broken is None:
                raise
            return broken

    def _run(self, step: Step) -> StepResult:
        match step:
            case AddFile():
                return self._add(step)
            case RemoveFile():
                return self._remove_file(step)
            case MakeDirectory():
                return self._make_directory(step.location)
            case _:
                keep = isinstance(step, PruneDirectory)
                return self._remove_directory(step.location, keep=keep)

    def _broken_way(self, step: Step) -> StepResult | None:
        """The result of ``step`` when a name on the way to one of its places is missing or is
        not a directory; ``None`` when every name on the way is a directory.

        Each name is read with a ``stat``, so the port tells a file, a missing name and a
        directory apart with no adapter error.
        """
        removal = isinstance(step, RemoveFile | RemoveDirectory | PruneDirectory)
        for location in _places(step):
            for depth in range(1, len(location.names)):
                component = LakePath(location.names[:depth])
                found = self._storage.stat(component)
                if found is not None and found.kind == "dir":
                    continue
                if removal:
                    return StepResult(StepOutcome.DONE)
                missing = found is None
                reason = BlockReason.DIRECTORY_MISSING if missing else BlockReason.FOREIGN_ENTRY
                return StepResult.blocked(reason, component)
        return None

    def _add(self, step: AddFile) -> StepResult:
        target, temporary = step.target, step.temporary
        found = self._storage.stat(target)
        if _is_file(found, step.new_inode):
            self._storage.remove_file(temporary, inode=step.new_inode)
            return self._done(target)
        expected = found is None if step.old_inode is None else _is_file(found, step.old_inode)
        if not expected:
            foreign = StepResult.blocked(BlockReason.FOREIGN_ENTRY, target)
            return self._broken_way(step) or foreign
        if not _is_file(self._storage.stat(step.source), step.new_inode):
            missing = StepResult.blocked(BlockReason.OBJECT_MISSING, step.source)
            return self._broken_way(step) or missing
        linked = self._storage.stat(temporary)
        if linked is None:
            self._storage.link_once(step.source, temporary)
        elif not _is_file(linked, step.new_inode):
            return StepResult.blocked(BlockReason.FOREIGN_ENTRY, temporary)
        self._storage.sync_directory(target.parent)
        self._storage.rename(temporary, target)
        return self._done(target)

    def _remove_file(self, step: RemoveFile) -> StepResult:
        if self._storage.remove_file(step.target, inode=step.old_inode) is Outcome.KEPT:
            return StepResult.blocked(BlockReason.FOREIGN_ENTRY, step.target)
        return self._absent(step.target)

    def _make_directory(self, location: LakePath) -> StepResult:
        found = self._storage.stat(location)
        if found is None:
            self._storage.make_inheriting_dir(location)
        elif found.kind != "dir":
            return StepResult.blocked(BlockReason.FOREIGN_ENTRY, location)
        return self._done(location)

    def _remove_directory(self, location: LakePath, *, keep: bool) -> StepResult:
        found = self._storage.stat(location)
        if found is not None:
            if found.kind != "dir":
                return StepResult.blocked(BlockReason.FOREIGN_ENTRY, location)
            if self._storage.remove_directory(location) is Outcome.KEPT:
                if keep:
                    return StepResult(StepOutcome.KEPT)
                return StepResult.blocked(BlockReason.DIRECTORY_NOT_EMPTY, location)
        return self._absent(location)

    def _done(self, location: LakePath) -> StepResult:
        """Sync the directory that holds ``location``; the step is done."""
        self._storage.sync_directory(location.parent)
        return StepResult(StepOutcome.DONE)

    def _absent(self, location: LakePath) -> StepResult:
        """``location`` is gone: sync the directory that held it, when that directory exists.

        No sync is possible for a directory that is gone; the name is gone with it.
        """
        if self._storage.stat(location.parent) is None:
            return StepResult(StepOutcome.DONE)
        return self._done(location)


_DETAILS = {
    BlockReason.FOREIGN_ENTRY: (
        "{path} is not the entry that the request expects. Huron did not change it."
    ),
    BlockReason.DIRECTORY_MISSING: (
        "The directory {path} does not exist. The request expects this directory."
    ),
    BlockReason.DIRECTORY_NOT_EMPTY: (
        "The directory {path} contains an entry that Huron did not record."
        " Huron did not remove the directory."
    ),
    BlockReason.OBJECT_MISSING: "The sealed object {path} does not exist or is another file.",
    BlockReason.SYMBOLIC_LINK: (
        "{path} is a symbolic link. The lake must not contain symbolic links. Remove it."
    ),
    BlockReason.INODE_UNKNOWN: (
        "Huron does not know the inode of {path}. Huron did not remove it."
    ),
}


def _places(step: Step) -> tuple[LakePath, ...]:
    """The places of ``step`` whose way must be directories: the target and the object of an
    add.
    """
    match step:
        case AddFile():
            return step.target, step.source
        case RemoveFile():
            return (step.target,)
        case _:
            return (step.location,)


def _is_file(found: Stat | None, inode: int) -> bool:
    return found is not None and found.kind == "file" and found.inode == inode


def _below(location: LakePath, directory: LakePath) -> bool:
    """Whether ``location`` lies below ``directory``, not at it."""
    depth = len(directory.names)
    return len(location.names) > depth and location.names[:depth] == directory.names
