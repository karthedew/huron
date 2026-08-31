"""Crash-safe POSIX publication primitives."""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class CrossDeviceCommitError(OSError):
    pass


def fsync_dir(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(directory: Path) -> None:
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
    staging_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)
    if staging_root.stat().st_dev != final_root.stat().st_dev:
        raise CrossDeviceCommitError(
            errno.EXDEV,
            f"staging and final roots cross filesystems: {staging_root} -> {final_root}",
        )


def commit_envelope(staging: Path, final: Path) -> None:
    """Durably publish one complete staging envelope with a single rename."""
    if final.exists():
        if not staging.exists() and (final / "COMMITTED").is_file():
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
        os.rename(staging, final)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise CrossDeviceCommitError(exc.errno, str(exc)) from exc
        raise
    fsync_dir(final.parent)
