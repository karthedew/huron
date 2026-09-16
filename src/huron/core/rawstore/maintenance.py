"""Read-only legacy inventory and durable write-once protocol evidence."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .materialize import candidate, descendant, directory, install

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class MaintenanceStore:
    """Inspect a root without following links or interpreting catalog documents."""

    def __init__(self, root: Path, owner_uid: int) -> None:
        """Bind an existing storage root and its deployment-assigned file owner.

        Args:
            root: Existing local POSIX storage root.
            owner_uid: Required owner of revision directories and regular files.
        """
        self._root = root
        self._owner_uid = owner_uid

    def revision_paths(self) -> Iterator[str]:
        """Enumerate every Raw revision name through no-follow parent descriptors.

        Final entry kinds are inspected separately so a corrupt known envelope can
        retain its database identity. Unsafe parent traversal remains a blocker.

        Yields:
            Paths relative to the held storage root, in deterministic order.
        """
        with directory(self._root) as root:
            yield from _revision_paths(root, (), ("organization", "project", "dataset"))

    def generation_paths(self) -> Iterator[str]:
        """Enumerate every structural generation and CURRENT pointer through held directories.

        Yields:
            Root-relative control paths, retaining missing-pointer and missing-chain failures.
        """
        with directory(self._root) as root:
            yield from _generation_paths(root, (), ("organization", "project", "dataset"))

    def read_generation(self, path: str) -> bytes:
        """Read a sealed hierarchy document whose inode is independent and correctly owned.

        Args:
            path: Relative structural control path from the complete inventory.

        Returns:
            Exact stored document bytes.
        """
        parts = _relative(path)
        with directory(self._root) as root, descendant(root, parts[:-1]) as parent:
            return _read_document(parent, parts[-1], self._owner_uid)

    def read_control(self, revision_path: str, name: str) -> bytes:
        """Read a bounded control document through a no-follow regular-file descriptor.

        Args:
            revision_path: Relative revision directory.
            name: Single control-document name.

        Returns:
            Exact bytes, retaining their original canonical or corrupt spelling.

        Raises:
            ValueError: If the path, file kind or document size is unsafe.
        """
        parts = _relative(revision_path)
        if _relative(name) != (name,):
            raise ValueError("control document must have one component")
        with directory(self._root) as root, descendant(root, parts) as parent:
            return _read_document(parent, name, None)

    def inspect_revision(
        self, revision_path: str, expected: Mapping[str, tuple[int, str]] | None
    ) -> tuple[str, ...]:
        """Stream all regular files and check owner, seals, links and exact inventory.

        Corrupt files do not stop inspection of their healthy siblings. Unsafe
        names are never followed, and findings contain codes without payload details.

        Args:
            revision_path: Relative revision directory.
            expected: Complete document and payload inventory, or None when corrupt
                documents prevent reconstructing the declared inventory.

        Returns:
            Sorted unique finding codes for every observed integrity failure.
        """
        findings: set[str] = set()
        observed: dict[str, tuple[int, str]] = {}
        with (
            directory(self._root) as root,
            descendant(root, _relative(revision_path)) as revision,
        ):
            _inspect_tree(revision, "", self._owner_uid, observed, findings)
        if expected is not None and observed != _complete_inventory(expected):
            findings.add("INVENTORY_MISMATCH")
        return tuple(sorted(findings))

    def write_evidence(self, relative_path: str, payload: bytes) -> None:
        """Install complete, closed, fsynced protocol evidence without replacement.

        Args:
            relative_path: Protocol-relative record or report path.
            payload: Complete canonical bytes prepared by the authorized workflow.

        Unsafe paths or conflicting existing evidence propagate ValueError.
        """
        parts = _relative(relative_path)
        with (
            directory(self._root) as root,
            descendant(root, ("protocol",), create=True) as protocol,
            descendant(protocol, ("workspace",), create=True) as workspace,
            descendant(protocol, parts[:-1], create=True) as parent,
            candidate(workspace, (payload,)) as name,
        ):
            install(
                workspace,
                name,
                parent,
                parts[-1],
                (len(payload), hashlib.sha256(payload).hexdigest()),
            )

    @contextmanager
    def claim(self) -> Iterator[None]:
        """Exclusively own this local root until all maintenance I/O has settled.

        The lock inode is never unlinked. Kernel ownership spans independent
        processes and is released by process death, never by a timer.

        Yields:
            Exclusive authority over maintenance observations and writes.

        Raises:
            ValueError: If the lock inode is not private, independent and locally owned.
        """
        with directory(self._root) as root, descendant(root, ("protocol",), create=True) as parent:
            descriptor = os.open(
                ".maintenance.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=parent,
            )
            try:
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                ):
                    raise ValueError("maintenance lock requires a private independent owned inode")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                os.close(descriptor)


def _relative(value: str) -> tuple[str, ...]:
    parts = value.split("/")
    if not value or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe maintenance path")
    return tuple(parts)


def _read_document(parent: int, name: str, owner_uid: int | None) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 << 20:
            raise ValueError("control document is not a bounded regular file")
        if owner_uid is not None:
            findings: set[str] = set()
            _check_attributes(info, owner_uid, findings)
            if findings:
                raise ValueError(
                    "structural document ownership, seal or independent inode is invalid"
                )
        return _read_control(descriptor)
    finally:
        os.close(descriptor)


def _generation_paths(
    parent: int, prefix: tuple[str, ...], kinds: tuple[str, ...]
) -> Iterator[str]:
    if not kinds or kinds[0] not in os.listdir(parent):
        return
    kind = kinds[0]
    with descendant(parent, (kind,)) as collection:
        for name in sorted(os.listdir(collection)):
            path = (*prefix, kind, name)
            with descendant(collection, (name,)) as entity:
                yield str(PurePosixPath(*path, "CURRENT.json"))
                with descendant(entity, ("generations",)) as generations:
                    for document in sorted(os.listdir(generations)):
                        yield str(PurePosixPath(*path, "generations", document))
                yield from _generation_paths(entity, path, kinds[1:])


def _complete_inventory(expected: Mapping[str, tuple[int, str]]) -> dict[str, tuple[int, str]]:
    complete = dict(expected)
    complete["payload"] = (-1, "")
    for path in expected:
        complete.update(
            (str(parent), (-1, "")) for parent in PurePosixPath(path).parents if str(parent) != "."
        )
    return complete


def _revision_paths(parent: int, prefix: tuple[str, ...], kinds: tuple[str, ...]) -> Iterator[str]:
    kind = kinds[0] if kinds else "raw"
    if kind not in os.listdir(parent):
        return
    with descendant(parent, (kind,)) as collection:
        if not kinds:
            if "revision" in os.listdir(collection):
                with descendant(collection, ("revision",)) as revisions:
                    for name in sorted(os.listdir(revisions)):
                        yield str(PurePosixPath(*prefix, "raw", "revision", name))
            return
        for name in sorted(os.listdir(collection)):
            with descendant(collection, (name,)) as entity:
                yield from _revision_paths(entity, (*prefix, kind, name), kinds[1:])


def _chunks(descriptor: int) -> Iterator[bytes]:
    while block := os.read(descriptor, 1 << 20):
        yield block


def _read_control(descriptor: int) -> bytes:
    blocks: list[bytes] = []
    size = 0
    for block in _chunks(descriptor):
        size += len(block)
        if size > 64 << 20:
            raise ValueError("control document exceeded its byte bound")
        blocks.append(block)
    return b"".join(blocks)


def _inspect_tree(
    descriptor: int,
    prefix: str,
    owner_uid: int,
    observed: dict[str, tuple[int, str]],
    findings: set[str],
) -> None:
    _check_attributes(os.fstat(descriptor), owner_uid, findings)
    if prefix:
        observed[prefix] = (-1, "")
    for name in sorted(os.listdir(descriptor)):
        path = str(PurePosixPath(prefix, name))
        try:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                with descendant(descriptor, (name,)) as child:
                    _inspect_tree(child, path, owner_uid, observed, findings)
            elif stat.S_ISREG(info.st_mode):
                _inspect_file(descriptor, name, path, owner_uid, observed, findings)
            else:
                findings.add("UNSAFE_ENTRY")
        except OSError:
            findings.add("ENTRY_IO_ERROR")


def _check_attributes(info: os.stat_result, owner_uid: int, findings: set[str]) -> None:
    if info.st_uid != owner_uid:
        findings.add("WRONG_OWNER")
    if info.st_mode & 0o222:
        findings.add("UNSEALED")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        findings.add("SHARED_INODE")


def _inspect_file(
    parent: int,
    name: str,
    path: str,
    owner_uid: int,
    observed: dict[str, tuple[int, str]],
    findings: set[str],
) -> None:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            findings.add("UNSAFE_ENTRY")
            return
        _check_attributes(info, owner_uid, findings)
        digest = hashlib.sha256()
        size = 0
        for block in _chunks(descriptor):
            digest.update(block)
            size += len(block)
        observed[path] = size, digest.hexdigest()
    finally:
        os.close(descriptor)
