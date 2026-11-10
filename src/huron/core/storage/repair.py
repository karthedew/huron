"""Repair of one planned directory: make it, fix its permission bits, try the catalog's group
and write ``metadata.json``.

A repair acts only on the directory of its step and lists no directory. ``chmod`` by a caller
outside a directory's group clears the setgid bit without an error, so a repair changes a mode
only while this process is in the directory's group. Below the organization's directory it
never sets a setgid bit, and it changes a group only on the catalog's directory (the share
group). A missing setgid bit or a wrong group below the organization's directory is the storage
administrator's work.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from huron.core.storage.errors import (
    InheritanceFailed,
    LakeUnavailable,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.lakepath import LakePath
from huron.core.storage.ports import GroupOutcome
from huron.schema.naming import METADATA_FILE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from huron.core.storage.directories import DirectoryWriter
    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.ports import ShareWarning, Stat, Storage

__all__ = ["FailureReason", "RepairFailure", "RepairResult", "RepairStep", "Repairer"]

#: What the storage administrator runs to give the directories below a catalog their setgid bit
#: and their group.
_PROVISION = "The storage administrator must run huron adm provision-catalogs."


class FailureReason(StrEnum):
    """Why a repair could not fix a place."""

    MODE_DRIFT = "mode_drift"
    SYMBOLIC_LINK = "symbolic_link"
    STORAGE_FAILED = "storage_failed"


@dataclass(frozen=True, slots=True)
class RepairFailure:
    """A place that a repair could not fix, the reason, and a sentence about that place."""

    path: str
    reason: FailureReason
    detail: str

    @classmethod
    def of(
        cls, place: OrganizationPlace, reason: FailureReason, error: StorageError, where: LakePath
    ) -> RepairFailure:
        """The failure that ``error`` gives the step at ``where`` of the organization ``place``."""
        named = error.context.get("path")
        location = LakePath.parse(named) if isinstance(named, str) and named else where
        base = place.base
        inside = location.names[: len(base.names)] == base.names and location != base
        path = location.relative_to(base) if inside else str(location)
        return cls(path, reason, _detail(place, error))


@dataclass(frozen=True, slots=True)
class RepairResult:
    """What a repair changed, the share groups still pending, and what it could not fix.

    The paths in ``changed`` are in the API form, relative to the organization's base.
    """

    changed: tuple[str, ...] = ()
    warnings: tuple[ShareWarning, ...] = ()
    failed: tuple[RepairFailure, ...] = ()

    @classmethod
    def combine(cls, results: Iterable[RepairResult]) -> RepairResult:
        """Combine ``results`` into one result, in their order. Each path, warning and failure
        occurs once.
        """
        changed: dict[str, None] = {}
        warnings: dict[ShareWarning, None] = {}
        failed: dict[RepairFailure, None] = {}
        for result in results:
            changed.update(dict.fromkeys(result.changed))
            warnings.update(dict.fromkeys(result.warnings))
            failed.update(dict.fromkeys(result.failed))
        return cls(tuple(changed), tuple(warnings), tuple(failed))


@dataclass(frozen=True, slots=True)
class RepairStep:
    """The repair of the directory at ``location`` of the organization ``place``.

    ``catalog`` is the catalog's directory, ``None`` for the organization's own directory. On
    the catalog's directory the step tries the group of ``share_group`` (the service group for
    ``None``). ``metadata`` is the ``metadata.json`` of a settled collection, ``None`` for any
    other directory.
    """

    place: OrganizationPlace
    location: LakePath
    catalog: LakePath | None
    share_group: str | None = None
    metadata: bytes | None = None

    def api_path(self, location: LakePath) -> str:
        """``location`` in the API form, relative to the organization's base."""
        return location.relative_to(self.place.base)


class Repairer:
    """Runs one :class:`RepairStep` at a time and lists no directory.

    Of the directories, it deletes only a directory that it made without the mode ``2750`` or
    without the group of its parent. Before it writes ``metadata.json``, it deletes the part
    file ``metadata.json.huron-part`` that an earlier write left. When the write fails, it
    tries to delete its own part file.
    """

    def __init__(self, storage: Storage, writer: DirectoryWriter) -> None:
        self._storage = storage
        self._writer = writer

    def repair(self, step: RepairStep) -> RepairResult:
        """Repair the directory of ``step``, in this order.

        1. Read the directory with one ``stat``. Make a missing directory
           (:meth:`DirectoryWriter.make`).
        2. Check the setgid bit on the catalog's directory and below it. Below it, also check
           that the directory has the group of the catalog's directory. Set other wrong
           permission bits.
        3. On the catalog's directory, try the share group. A refusal gives a
           ``SHARE_GROUP_PENDING`` warning.
        4. For a settled collection, write ``metadata.json`` when its bytes differ.

        The first failure ends the step. The result keeps the failure and what changed before
        it. The method raises only ``LAKE_UNAVAILABLE``. The Field descriptions of the API
        schema ``RepairFailureOut`` give the ``path``, ``reason`` and ``detail`` of a failure.
        """
        progress = _Progress(step)
        try:
            self._run(step, progress)
        except LakeUnavailable:
            raise
        except _Drift as drift:
            path = step.api_path(step.location)
            return progress.result(RepairFailure(path, FailureReason.MODE_DRIFT, drift.detail))
        except StorageError as error:
            failure = RepairFailure.of(step.place, _reason(error), error, step.location)
            return progress.result(failure)
        return progress.result()

    def _run(self, step: RepairStep, progress: _Progress) -> None:
        location = step.location
        found = self._storage.stat(location)
        if found is None:
            if self._writer.make(step.place, location):
                progress.changed.append(location)
        elif found.kind != "dir":
            raise StorageError(
                f"{step.api_path(location)} is not a directory", {"path": str(location)}
            )
        elif self._mode(step, found):
            progress.changed.append(location)
        if location == step.catalog:
            result = self._writer.set_group(location, step.share_group)
            if result.outcome is GroupOutcome.CHANGED:
                progress.changed.append(location)
            elif (warning := result.warning(self._writer.group_for(step.share_group))) is not None:
                progress.warnings.append(warning)
        if step.metadata is not None and self._writer.write_metadata(location, step.metadata):
            progress.changed.append(location.joinpath(METADATA_FILE))

    def _mode(self, step: RepairStep, found: Stat) -> bool:
        """Give the directory its mode, and return whether the mode changed.

        Raises :class:`_Drift`.
        """
        location, path = step.location, step.api_path(step.location)
        if step.catalog is not None:
            if not found.mode & stat.S_ISGID:
                raise _Drift(f"{path} does not have the setgid bit. {_PROVISION}")
            catalog_gid = self._gid(step.catalog)
            if location != step.catalog and found.gid != catalog_gid:
                raise _Drift(
                    f"{path} has the group {found.gid}, not the group {catalog_gid} of the"
                    f" catalog directory. {_PROVISION}"
                )
        expected = step.place.mode_of(location)
        if found.mode == expected:
            return False
        if not self._storage.in_group(found.gid):
            raise _Drift(
                f"The API is not in the group {found.gid} of {path}. Thus the API cannot change"
                f" the mode {found.mode:o} to {expected:o}."
            )
        self._storage.set_mode(location, expected)
        if self._mode_of(location) != expected:
            raise _Drift(f"The mode of {path} is not {expected:o} after the change. {_PROVISION}")
        return True

    def _gid(self, location: LakePath) -> int | None:
        found = self._storage.stat(location)
        return None if found is None else found.gid

    def _mode_of(self, location: LakePath) -> int | None:
        found = self._storage.stat(location)
        return None if found is None else found.mode


@dataclass
class _Progress:
    """What one step changed so far, and its result."""

    step: RepairStep
    changed: list[LakePath] = field(default_factory=list)
    warnings: list[ShareWarning] = field(default_factory=list)

    def result(self, *failed: RepairFailure) -> RepairResult:
        paths = dict.fromkeys(self.step.api_path(location) for location in self.changed)
        return RepairResult(tuple(paths), tuple(self.warnings), failed)


def _reason(error: StorageError) -> FailureReason:
    if isinstance(error, InheritanceFailed):
        return FailureReason.MODE_DRIFT
    if isinstance(error, SymlinkInLake):
        return FailureReason.SYMBOLIC_LINK
    return FailureReason.STORAGE_FAILED


def _detail(place: OrganizationPlace, error: StorageError) -> str:
    """The error's message, with the path that it names in the API form."""
    named = str(error.context.get("path", ""))
    prefix = f"{place.base}/"
    if place.base.names and named.startswith(prefix):
        # A storage message names its path before the system's reason, so only the first
        # occurrence is the path: a reason such as "Input/output error" stays as it is.
        return error.message.replace(named, named.removeprefix(prefix), 1)
    return error.message


class _Drift(Exception):
    """A mode that only the storage administrator can fix. ``detail`` says why."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
