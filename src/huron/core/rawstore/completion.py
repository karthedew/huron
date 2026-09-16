"""Bound verified completion copies and reserve their expected filesystem capacity."""

from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class CompletionAdmission:
    """Coordinate completion copies sharing one admission object in one process.

    A slot bounds concurrent copies. Capacity reservations conservatively count
    every admitted copy's entire expected size until it finishes, even when its
    bytes already consume disk space. Other processes, uploads and held upload
    descriptors can still consume space; this object does not fence those writers.
    """

    def __init__(self, *, max_concurrent: int, reserve_bytes: int) -> None:
        """Configure copy concurrency and free space retained after reservations.

        Args:
            max_concurrent: Maximum simultaneous completion copies.
            reserve_bytes: Minimum unreserved filesystem capacity to retain.

        Raises:
            ValueError: If concurrency is not positive or the reserve is negative.
        """
        if max_concurrent < 1:
            raise ValueError("completion concurrency must be positive")
        if reserve_bytes < 0:
            raise ValueError("completion disk reserve cannot be negative")
        self._slots = BoundedSemaphore(max_concurrent)
        self._lock = Lock()
        self._reserve_bytes = reserve_bytes
        self._reserved_bytes = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Hold a copy slot while rechecking installed payload and materializing it.

        Recheck for an installed winner after acquiring the slot. A waiting
        retry can then return existing verified bytes without reserving space.

        Yields:
            Control while the completion slot remains held.
        """
        with self._slots:
            yield

    @contextmanager
    def reserve(self, directory: int, expected_size: int) -> Iterator[None]:
        """Reserve expected copy bytes before any candidate is created.

        Call inside a held slot only when the payload still needs a copy. The
        accounting remains held through candidate cleanup and installation and
        is released on success, failure or cancellation.

        Args:
            directory: Held descriptor of the candidate filesystem directory.
            expected_size: Declared complete file size to reserve.

        Yields:
            Control while the expected copy capacity remains reserved.

        Raises:
            ValueError: If the expected file size is negative.
            OSError: If free capacity cannot retain all reservations and the reserve.
        """
        if expected_size < 0:
            raise ValueError("expected completion size cannot be negative")
        with self._lock:
            filesystem = os.fstatvfs(directory)
            available = filesystem.f_bavail * filesystem.f_frsize
            required = self._reserved_bytes + expected_size + self._reserve_bytes
            if available < required:
                raise OSError(
                    errno.ENOSPC,
                    f"completion requires {required} free bytes; {available} are available",
                )
            self._reserved_bytes += expected_size
        try:
            yield
        finally:
            with self._lock:
                self._reserved_bytes -= expected_size
