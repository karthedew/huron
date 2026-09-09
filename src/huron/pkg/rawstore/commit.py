"""Crash-safe POSIX publication primitives.

Everything the raw layer publishes goes through the same two steps: make
the staged bytes durable, then reveal them under their final name with one
``rename``. :func:`fsync_tree` and :func:`fsync_dir` are the first step -
the directories on the path are flushed as well as the files, so the names
are as durable as the bytes. :func:`commit_envelope` is the second, and it
refuses ahead of time whenever the rename could not be atomic or would
replace something: a staging and a final root on different filesystems
(:func:`assert_same_filesystem` checks this at startup and
:class:`CrossDeviceCommitError` reports it) or a final name that already
exists.
"""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING

from .materialize import directory, rename_exclusive

if TYPE_CHECKING:
    from pathlib import Path


class CrossDeviceCommitError(OSError):
    """Staging and final paths sit on different filesystems, so no atomic rename joins them.

    Carries ``errno.EXDEV``. It is raised before any rename is attempted
    when the two device numbers differ, and again if the rename itself
    fails with ``EXDEV``; either way nothing has been published.
    """


def fsync_dir(directory: Path) -> None:
    """Flush a directory's entries to stable storage.

    Opens the directory read-only and fsyncs the descriptor. This is the
    step that makes a rename, a newly created name or a removal durable
    once the bytes behind it already are; fsyncing the file alone does not
    persist the entry that names it.

    Args:
        directory: An existing directory; the open uses ``O_DIRECTORY``, so
            any other kind of path fails.
    """
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(directory: Path) -> None:
    """Flush every file and directory under ``directory``, then ``directory`` itself.

    Files go first, then directories from the deepest up, then the root,
    so each directory is flushed only after everything it names is already
    durable. Once it returns the whole subtree survives a crash, which is
    the precondition for publishing it with a single rename.

    Args:
        directory: The root of the subtree to make durable.
    """
    for file_path in sorted(path for path in directory.rglob("*") if path.is_file()):
        descriptor = os.open(file_path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for child in sorted(
        (path for path in directory.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        fsync_dir(child)
    fsync_dir(directory)


def assert_same_filesystem(staging_root: Path, final_root: Path) -> None:
    """Refuse a layout in which staging and final roots cannot share a rename.

    Both roots are created if missing, then their device numbers are
    compared. :meth:`PosixRawStore.initialize` runs this at startup so a
    deployment whose staging area is on a different filesystem from its
    data fails before the first ingest rather than at its commit.

    Args:
        staging_root: The directory envelopes are built under.
        final_root: The directory they are published under.

    Raises:
        CrossDeviceCommitError: If the two roots report different ``st_dev``.
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)
    if staging_root.stat().st_dev != final_root.stat().st_dev:
        raise CrossDeviceCommitError(
            errno.EXDEV,
            f"staging and final roots cross filesystems: {staging_root} -> {final_root}",
        )


def commit_envelope(staging: Path, final: Path) -> None:
    """Durably publish one complete staging envelope with a single rename.

    The envelope is a directory the caller has finished writing and marked
    with a ``COMMITTED`` file. Publication is: every file and directory in
    it is fsynced, the directory is renamed to ``final`` in one
    ``os.rename``, ``final``'s parent is fsynced so the new name is as
    durable as its contents, and then ``final`` itself is made ``0o555``
    and fsynced. Nothing is visible under ``final`` before the rename and
    the rename is the only step that changes what is visible there, so a
    crash at any point leaves either the staging directory as it was or
    the complete published envelope, never a partial one.

    An existing ``final`` is never overwritten. The one case that is not
    refused is the retry: when ``staging`` is already gone and ``final``
    carries ``COMMITTED``, the caller must first validate its full frozen
    evidence. The call flushes both rename parents and reseals ``final``,
    so a caller that crashed between the rename and its own bookkeeping
    or between the rename and the seal can safely run again.

    Args:
        staging: The finished envelope; must be a directory containing a
            ``COMMITTED`` file.
        final: The path to publish it at; its parent is created if missing
            and must be on the same filesystem as ``staging``.

    Raises:
        FileExistsError: If ``final`` exists and this is not a completed
            retry.
        FileNotFoundError: If ``staging`` is not a directory.
        ValueError: If ``staging`` has no ``COMMITTED`` marker; an unmarked
            envelope is unfinished and must not be published.
        CrossDeviceCommitError: If ``staging`` and ``final``'s parent are on
            different filesystems, whether detected before the rename or
            reported by it as ``EXDEV``.
        OSError: If the rename fails for any other reason; re-raised
            unchanged.
    """
    if final.exists():
        if not staging.exists() and (final / "COMMITTED").is_file():
            # The name may be visible even though the interrupted rename's
            # directory updates have not reached stable storage.
            fsync_dir(staging.parent)
            fsync_dir(final.parent)
            os.chmod(final, 0o555)
            fsync_dir(final)
            return
        raise FileExistsError(final)
    if not staging.is_dir():
        raise FileNotFoundError(staging)
    if not (staging / "COMMITTED").is_file():
        raise ValueError("refusing to publish an envelope without COMMITTED")
    final.parent.mkdir(parents=True, exist_ok=True)
    if staging.stat().st_dev != final.parent.stat().st_dev:
        raise CrossDeviceCommitError(errno.EXDEV, f"cross-device commit: {staging} -> {final}")
    fsync_tree(staging)
    try:
        with directory(staging.parent) as source, directory(final.parent) as target:
            rename_exclusive(source, staging.name, target, final.name)
            os.fsync(source)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise CrossDeviceCommitError(exc.errno, str(exc)) from exc
        raise
    fsync_dir(final.parent)
    # Sealing before the rename would make the root un-renameable by a
    # non-root user - rename(2) needs write access on the directory being
    # moved to update its own `..` entry - so the seal happens only once
    # publication is already durable.
    os.chmod(final, 0o555)
    fsync_dir(final)
