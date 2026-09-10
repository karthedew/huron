"""Read-only validation of a complete publication envelope."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .materialize import descendant, directory, observe

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def verify_envelope(
    envelope: Path,
    files: Sequence[tuple[str, int, str]],
    documents: Mapping[str, bytes],
    *,
    sealed: bool = False,
    anchor: Path | None = None,
) -> None:
    """Validate exact inventory, independent sealed files and frozen document bytes.

    Inventory or file-evidence disagreement propagates ``ValueError`` from inspection.

    Args:
        envelope: Existing envelope to inspect without mutation.
        files: Manifest paths, complete sizes and content digests.
        documents: Exact immutable control document bytes.
        sealed: Require sealed descendant directories; the root may await its final seal.
        anchor: Trusted storage root for component-by-component traversal.
    """
    expected = {
        name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in documents.items()
    }
    expected.update({path: (size, digest) for path, size, digest in files})
    directories = {"payload"}
    for path in expected:
        directories.update(
            str(parent) for parent in PurePosixPath(path).parents if str(parent) != "."
        )
    with directory(envelope, anchor=anchor) as root:
        _verify_directory(root, ".", sealed=False)
        _verify_tree(root, "", expected, directories, sealed=sealed)


def _verify_tree(
    root: int,
    prefix: str,
    expected: Mapping[str, tuple[int, str]],
    directories: set[str],
    *,
    sealed: bool,
) -> None:
    parent = PurePosixPath(prefix)
    wanted = {
        PurePosixPath(path).name
        for path in set(expected) | directories
        if PurePosixPath(path).parent == parent
    }
    if set(os.listdir(root)) != wanted:
        raise ValueError(f"envelope inventory disagrees at {prefix or '.'}")
    for name in sorted(wanted):
        path = str(parent / name)
        if path in directories:
            with descendant(root, (name,)) as child:
                _verify_directory(child, path, sealed=sealed)
                _verify_tree(child, path, expected, directories, sealed=sealed)
        elif observe(root, name) != expected[path]:
            raise ValueError(f"envelope content disagrees: {path}")


def _verify_directory(descriptor: int, path: str, *, sealed: bool) -> None:
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or (sealed and info.st_mode & 0o222):
        raise ValueError(f"envelope directory ownership or seal disagrees: {path}")
