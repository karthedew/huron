"""Read-only validation of a complete publication envelope."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .materialize import descendant, directory, observe

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def verify_envelope(
    envelope: Path, files: Sequence[tuple[str, int, str]], documents: Mapping[str, bytes]
) -> None:
    """Validate exact inventory, independent sealed files and frozen document bytes.

    Inventory or file-evidence disagreement propagates ``ValueError`` from inspection.

    Args:
        envelope: Existing envelope to inspect without mutation.
        files: Manifest paths, complete sizes and content digests.
        documents: Exact immutable control document bytes.
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
    with directory(envelope) as root:
        _verify_tree(root, "", expected, directories)


def _verify_tree(
    root: int, prefix: str, expected: Mapping[str, tuple[int, str]], directories: set[str]
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
                info = os.fstat(child)
                if info.st_uid != os.geteuid() or not stat.S_ISDIR(info.st_mode):
                    raise ValueError(f"envelope directory ownership disagrees: {path}")
                _verify_tree(child, path, expected, directories)
        elif observe(root, name) != expected[path]:
            raise ValueError(f"envelope content disagrees: {path}")
