"""The local source files of a working copy: what ``huron add`` records and ``huron push`` checks.

``huron add`` records the size, the modification time and the sha256 of each file. ``huron push``
opens the file again without following a link, and sends it only when its size and modification
time are the recorded ones. The commit sends the recorded sha256, and the service compares it with
the sha256 of the sealed bytes, so a change that keeps the size and the modification time still
fails the commit. The CLI makes no copy of a source file.
"""

from __future__ import annotations

import errno
import os
import shlex
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.localstate import StagedAdd
from huron.pkg.hashing import sha256_descriptor
from huron.schema.naming import RelPathError, check_rel_path, is_storage_name, rel_path_key

__all__ = ["SkippedEntry", "collect_sources", "open_source", "source_changed"]

#: Open a source file for reading, never through a link. A FIFO does not block the open.
_READ_SOURCE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_LINK = "it is a symbolic link"
_NOT_REGULAR = "it is not a regular file"
_STORAGE_NAME = "a collection cannot have this name"


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    """An entry below a staged directory that ``huron add`` did not stage; ``reason`` says why."""

    path: Path
    reason: str


def collect_sources(
    paths: list[Path], rename: str | None, recursive: bool
) -> tuple[list[StagedAdd], list[SkippedEntry]]:
    """The adds of the regular files at ``paths``, and the entries that the walk skipped.

    A named path must be a regular file, or a directory with ``recursive``; ``rename`` gives its
    one file another path in the collection. The walk of a directory does not follow links. It
    skips a link, an entry that is not a regular file or a directory, and an entry that it cannot
    read. It also skips each entry named ``.snapshot`` or ``.nfs*``, which a storage or an NFS
    client can make (:func:`~huron.schema.naming.is_storage_name`), and does not enter it. The
    path rules refuse these names, so a named file with such a name, or ``rename`` with such a
    segment, refuses the add. A path that breaks a path rule, and two paths that are the same in
    a collection, refuse the whole add before the CLI reads a file.
    """
    if rename is not None and len(paths) != 1:
        raise UsageError("`--as` needs exactly one file")
    skipped: list[SkippedEntry] = []
    found = [item for path in paths for item in _collect(path, rename, recursive, skipped)]
    _check_paths(found)
    staged: list[StagedAdd] = []
    for candidate in found:
        try:
            staged.append(_record(candidate.path, candidate.rel_path))
        except _Unstageable as error:
            if candidate.named:
                raise UsageError(f"the CLI cannot stage {candidate.path}: {error.reason}") from None
            skipped.append(SkippedEntry(candidate.path, error.reason))
    return staged, skipped


def open_source(add: StagedAdd) -> BinaryIO:
    """Open the source file of ``add`` to send it, without following a link.

    Refuses a file that is not the regular file with the size and the modification time that
    ``huron add`` recorded, and a file that the CLI cannot open.
    """
    try:
        descriptor = os.open(add.source, _READ_SOURCE)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise source_changed(add) from error
        raise CliError(
            f"the CLI cannot read {add.source}, which you staged as {add.rel_path}:"
            f" {error.strerror}",
            ExitCode.USAGE,
            hint=_stage_again(add),
        ) from error
    info = os.fstat(descriptor)
    recorded = (add.size, add.mtime_ns)
    if not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns) != recorded:
        os.close(descriptor)
        raise source_changed(add)
    return os.fdopen(descriptor, "rb")


def source_changed(add: StagedAdd) -> CliError:
    """The error for a staged file that changed after ``huron add``."""
    return CliError(
        f"{add.source} changed after you staged it as {add.rel_path}",
        ExitCode.USAGE,
        hint=_stage_again(add),
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A file to stage at ``rel_path``; ``named`` when the command line names it."""

    path: Path
    rel_path: str
    named: bool


class _Unstageable(Exception):
    """A file that the CLI cannot stage; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _collect(
    path: Path, rename: str | None, recursive: bool, skipped: list[SkippedEntry]
) -> list[_Candidate]:
    """The files to stage for one named path; a directory adds the entries it skips."""
    try:
        directory = stat.S_ISDIR(path.lstat().st_mode)
    except OSError as error:
        raise UsageError(f"the CLI cannot stage {path}: {error.strerror}") from error
    if not directory:
        return [_Candidate(path, rename or path.name, named=True)]
    if not recursive:
        raise UsageError(f"{path} is a directory", hint="use `--recursive`")
    return list(_walk(path, path, skipped))


def _walk(top: Path, directory: Path, skipped: list[SkippedEntry]) -> Iterator[_Candidate]:
    """The regular files below ``directory``, by name, at their paths relative to ``top``."""
    try:
        with os.scandir(directory) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
    except OSError as error:
        skipped.append(SkippedEntry(directory, str(error.strerror)))
        return
    for entry in entries:
        path = Path(entry.path)
        if is_storage_name(entry.name):
            skipped.append(SkippedEntry(path, _STORAGE_NAME))
        elif entry.is_symlink():
            skipped.append(SkippedEntry(path, _LINK))
        elif entry.is_dir(follow_symlinks=False):
            yield from _walk(top, path, skipped)
        elif entry.is_file(follow_symlinks=False):
            yield _Candidate(path, path.relative_to(top).as_posix(), named=False)
        else:
            skipped.append(SkippedEntry(path, _NOT_REGULAR))


def _check_paths(candidates: list[_Candidate]) -> None:
    """Refuse a path that breaks a path rule, and two files at the same path in a collection."""
    seen: dict[str, _Candidate] = {}
    for candidate in candidates:
        try:
            check_rel_path(candidate.rel_path)
        except RelPathError as error:
            raise UsageError(
                f"{candidate.rel_path!r} is not a valid path in a collection ({error.rule})"
            ) from error
        first = seen.setdefault(rel_path_key(candidate.rel_path), candidate)
        if first is not candidate:
            raise UsageError(
                f"{first.path} and {candidate.path} have the same path in a collection",
                hint=(
                    "paths that differ only in the case of letters are the same path in a"
                    " collection. To give one file a different path, run"
                    " `huron add <file> --as <path>`"
                ),
            )


def _record(path: Path, rel_path: str) -> StagedAdd:
    """The add of the regular file at ``path``, with its size, modification time and sha256.

    The last name of ``path`` is never followed as a link.
    """
    source = path.parent.resolve() / path.name
    try:
        info, digest = _read(source)
    except OSError as error:
        raise _Unstageable(_LINK if error.errno == errno.ELOOP else str(error.strerror)) from error
    return StagedAdd(rel_path, str(source), info.st_size, info.st_mtime_ns, digest)


def _read(source: Path) -> tuple[os.stat_result, str]:
    """The status and the sha256 of the regular file ``source``."""
    descriptor = os.open(source, _READ_SOURCE)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise _Unstageable(_NOT_REGULAR)
        return info, sha256_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _stage_again(add: StagedAdd) -> str:
    source, rel_path = shlex.quote(add.source), shlex.quote(add.rel_path)
    return (
        f"to stage the file again, run `huron add {source} --as {rel_path}`."
        f" To unstage it, run `huron rm {rel_path}`"
    )
