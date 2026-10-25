"""Anchored POSIX descriptors, complete writes and durable directory entries."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import sys
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def directory(path: Path, *, anchor: Path | None = None) -> Iterator[int]:
    """Hold an existing directory without following a link at its name.

    Args:
        path: Existing directory to open.
        anchor: Trusted root beneath which every component must be a real directory.

    Yields:
        A directory descriptor, closed when the context exits.

    Raises:
        ValueError: If the path traverses above its trusted root.
    """
    if anchor is not None:
        parts = path.relative_to(anchor).parts
        if ".." in parts:
            raise ValueError("directory escapes its trusted root")
        with directory(anchor) as root, descendant(root, parts) as descriptor:
            yield descriptor
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def descendant(parent: int, parts: tuple[str, ...], *, create: bool = False) -> Iterator[int]:
    """Traverse beneath a held directory without following links or recreating it.

    Args:
        parent: Existing ancestor descriptor.
        parts: Validated relative directory components.
        create: Whether missing descendants may be created privately.

    Yields:
        The final directory descriptor.
    """
    descriptor = os.dup(parent)
    try:
        for part in parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def rename_exclusive(source_dir: int, source: str, target_dir: int, target: str) -> None:
    """Rename without replacement, refusing unsupported platforms and filesystems.

    Args:
        source_dir: Directory holding the closed candidate.
        source: Candidate name.
        target_dir: Destination directory.
        target: Destination name that must not exist.

    Raises:
        OSError: If exclusive rename is unsupported or the system call fails.
    """
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flags = 4
    elif sys.platform == "linux":
        function = getattr(library, "renameat2", None)
        flags = 1
    else:
        raise OSError(errno.ENOTSUP, "exclusive rename is not supported on this platform")
    if function is None:
        raise OSError(errno.ENOTSUP, "exclusive rename is unavailable in the system library")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(source_dir, os.fsencode(source), target_dir, os.fsencode(target), flags) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def observe(parent: int, name: str, *, sealed: bool = True) -> tuple[int, str]:
    """Hash a regular independently owned file through a read-only descriptor.

    Args:
        parent: Existing parent directory descriptor.
        name: File name within that directory.
        sealed: Require read-only permissions when true.

    Returns:
        The streamed byte count and SHA-256 digest.

    Raises:
        ValueError: If the inode is not regular, independently owned or sealed.
    """
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or (sealed and info.st_mode & 0o222)
        ):
            raise ValueError(f"file is not independently owned and sealed: {name}")
        digest = hashlib.sha256()
        size = 0
        while block := os.read(descriptor, 1 << 20):
            size += len(block)
            digest.update(block)
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def write_all(descriptor: int, payload: bytes, *, offset: int | None = None) -> None:
    """Write complete bytes despite short writes, refusing a stalled filesystem.

    Args:
        descriptor: An open writable file descriptor.
        payload: Bytes to write completely.
        offset: Fixed range start, or the descriptor's current position when absent.

    Raises:
        OSError: If the filesystem reports no write progress.
    """
    remaining = memoryview(payload)
    while remaining:
        count = (
            os.write(descriptor, remaining)
            if offset is None
            else os.pwrite(descriptor, remaining, offset)
        )
        if count == 0:
            raise OSError(errno.EIO, "write made no progress")
        remaining = remaining[count:]
        if offset is not None:
            offset += count


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
