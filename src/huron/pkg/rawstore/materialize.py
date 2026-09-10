"""Closed, independent candidates installed with an exclusive rename."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import sys
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
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


@contextmanager
def candidate(parent: int, chunks: Iterable[bytes]) -> Iterator[str]:
    """Write, seal, fsync and close a private candidate before exposing its name.

    Args:
        parent: Existing private candidate directory descriptor.
        chunks: Bytes to copy into a newly allocated inode.

    Yields:
        The closed candidate name, removed on exit unless already renamed.
    """
    name = uuid4().hex
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
    try:
        try:
            for chunk in chunks:
                write_all(descriptor, chunk)
            os.fchmod(descriptor, 0o444)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)
        yield name
    finally:
        with suppress(FileNotFoundError):
            os.unlink(name, dir_fd=parent)
        os.fsync(parent)


def install(
    parent: int, name: str, target_dir: int, target: str, expected: tuple[int, str]
) -> None:
    """Install a closed candidate or verify the concurrent winner, durably.

    Args:
        parent: Candidate directory descriptor.
        name: Closed candidate name.
        target_dir: Destination parent descriptor.
        target: Installed file name.
        expected: Required byte count and SHA-256.

    Raises:
        ValueError: If an existing destination disagrees with the candidate.
    """
    try:
        rename_exclusive(parent, name, target_dir, target)
    except FileExistsError:
        if observe(target_dir, target) != expected:
            raise ValueError(f"installed file conflicts with verified content: {target}") from None
    os.fsync(target_dir)
    os.fsync(parent)


def file_chunks(parent: int, name: str) -> Iterator[bytes]:
    """Read an upload input without following links or accepting special files.

    Args:
        parent: Existing upload directory descriptor.
        name: Input file name.

    Yields:
        Bounded blocks from the upload input.

    Raises:
        ValueError: If the upload input is not a regular independent file.
    """
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError(f"upload input is not an independent regular file: {name}")
        while block := os.read(descriptor, 1 << 20):
            yield block
    finally:
        os.close(descriptor)


def flush_tree(root: int, *, seal: bool = False) -> None:
    """Flush a held tree, optionally sealing each descendant before its parent.

    Args:
        root: Existing directory descriptor; the root itself remains writable.
        seal: Whether to remove write permissions from all descendants.

    Raises:
        ValueError: If any file is not regular and independently owned.
    """
    for name in sorted(os.listdir(root)):
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with descendant(root, (name,)) as child:
                flush_tree(child, seal=seal)
                if seal:
                    os.fchmod(child, 0o555)
                    os.fsync(child)
        else:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
            try:
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                ):
                    raise ValueError(f"tree contains an unsafe file: {name}")
                if seal:
                    os.fchmod(descriptor, 0o444)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    os.fsync(root)
