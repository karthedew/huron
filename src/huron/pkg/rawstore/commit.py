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

from .materialize import descendant, directory, flush_tree, rename_exclusive

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


def commit_envelope(staging: Path, final: Path, root: Path) -> None:
    """Durably publish one complete staging envelope with a single rename.

    The envelope is a directory the caller has finished writing and marked
    with a ``COMMITTED`` file. Publication is: every file and directory in
    it is fsynced, the directory is renamed to ``final`` in one
    exclusive rename, ``final``'s parent is fsynced so the new name is as
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
        root: Trusted storage root containing both publication paths.

    Storage traversal propagates missing-path and existing-target errors. A device
    mismatch propagates ``CrossDeviceCommitError``; other I/O errors are unchanged.

    Raises:
        ValueError: If a path escapes the trusted root.
    """
    source_parts = staging.relative_to(root).parent.parts
    target_parts = final.relative_to(root).parent.parts
    if ".." in source_parts + target_parts:
        raise ValueError("publication path escapes its trusted root")
    with (
        directory(root) as anchor,
        descendant(anchor, source_parts) as source,
        descendant(anchor, target_parts, create=True) as target,
    ):
        _publish(source, staging.name, target, final.name)


def _publish(source: int, staged_name: str, target: int, final_name: str) -> None:
    try:
        os.stat(final_name, dir_fd=target, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        try:
            os.stat(staged_name, dir_fd=source, follow_symlinks=False)
        except FileNotFoundError:
            with descendant(target, (final_name,)) as published:
                os.stat("COMMITTED", dir_fd=published, follow_symlinks=False)
                _finish_publication(source, target, published)
            return
        raise FileExistsError(final_name)
    with descendant(source, (staged_name,)) as staged:
        try:
            os.stat("COMMITTED", dir_fd=staged, follow_symlinks=False)
        except FileNotFoundError:
            raise ValueError("refusing to publish an envelope without COMMITTED") from None
        if os.fstat(staged).st_dev != os.fstat(target).st_dev:
            raise CrossDeviceCommitError(errno.EXDEV, "cross-device commit")
        flush_tree(staged)
        try:
            rename_exclusive(source, staged_name, target, final_name)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise CrossDeviceCommitError(exc.errno, str(exc)) from exc
            raise
        _finish_publication(source, target, staged)


def _finish_publication(source: int, target: int, published: int) -> None:
    os.fsync(source)
    os.fsync(target)
    os.fchmod(published, 0o555)
    os.fsync(published)
