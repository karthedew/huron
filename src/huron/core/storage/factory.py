"""Build the storage the CLI uses."""

from __future__ import annotations

from typing import Literal

from huron.core.storage.posix import PosixStorage
from huron.pkg.fs.acl import SubprocessRunner

__all__ = ["storage_for"]


def storage_for(acl_backend: Literal["posix", "none"]) -> PosixStorage:
    """POSIX storage with ACLs written by ``setfacl`` (or only modes with ``"none"``)."""
    return PosixStorage(acl_backend, SubprocessRunner())
