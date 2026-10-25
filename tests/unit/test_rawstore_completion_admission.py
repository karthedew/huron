"""Completion admission bounds copies while retaining capacity for other storage work."""

from __future__ import annotations

import asyncio
import errno
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from typing import TYPE_CHECKING

import pytest

from huron.core.rawstore.completion import CompletionAdmission
from huron.core.rawstore.materialize import directory

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _free_capacity(monkeypatch: pytest.MonkeyPatch, available: int) -> None:
    filesystem = os.statvfs_result((1, 1, available, available, available, 0, 0, 0, 0, 255))
    monkeypatch.setattr(os, "fstatvfs", lambda _: filesystem)


@pytest.mark.parametrize("max_concurrent", [0, -1])
def test_completion_admission_requires_positive_concurrency(max_concurrent: int) -> None:
    """No configuration can create an admission object that permanently blocks every copy."""
    with pytest.raises(ValueError, match="concurrency must be positive"):
        CompletionAdmission(max_concurrent=max_concurrent, reserve_bytes=0)


def test_completion_admission_requires_a_nonnegative_reserve() -> None:
    """A negative reserve cannot turn insufficient disk space into admissible capacity."""
    with pytest.raises(ValueError, match="reserve cannot be negative"):
        CompletionAdmission(max_concurrent=1, reserve_bytes=-1)


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_only_the_configured_number_of_copies_can_enter(limit: int) -> None:
    """A waiting completion starts only after an occupied copy slot is released."""
    admission = CompletionAdmission(max_concurrent=limit, reserve_bytes=0)
    started, entered = Event(), Event()

    def copy() -> None:
        started.set()
        with admission.slot():
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with ExitStack() as occupied:
            for _ in range(limit):
                occupied.enter_context(admission.slot())
            waiting = executor.submit(copy)
            assert started.wait(10)
            assert not entered.wait(0.05)
        waiting.result(timeout=10)
    assert entered.is_set()


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_copy_failure_releases_both_capacity_and_slot(
    monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    """A failed or cancelled copy cannot strand its concurrency or capacity reservation."""
    _free_capacity(monkeypatch, 100)
    admission = CompletionAdmission(max_concurrent=1, reserve_bytes=25)
    with pytest.raises(failure), admission.slot(), admission.reserve(0, 75):
        raise failure()

    def retry() -> None:
        with admission.slot(), admission.reserve(0, 75):
            pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(retry).result(timeout=10)


def test_capacity_refusal_precedes_copy_and_does_not_leak_a_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copy that cannot retain the reserve never enters its body and a smaller retry fits."""
    _free_capacity(monkeypatch, 100)
    admission = CompletionAdmission(max_concurrent=1, reserve_bytes=25)
    with admission.slot():
        with pytest.raises(OSError) as error, admission.reserve(0, 76):
            pytest.fail("insufficient capacity admitted a copy")
        assert error.value.errno == errno.ENOSPC
        with admission.reserve(0, 75):
            pass


def test_concurrent_copies_account_for_each_others_expected_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free space is reserved atomically for every unfinished copy sharing admission."""
    _free_capacity(monkeypatch, 100)
    admission = CompletionAdmission(max_concurrent=2, reserve_bytes=25)

    def compete() -> None:
        with admission.slot():
            with pytest.raises(OSError) as error, admission.reserve(0, 40):
                pytest.fail("overlapping reservations exceeded available space")
            assert error.value.errno == errno.ENOSPC
            with admission.reserve(0, 35):
                pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        with admission.slot(), admission.reserve(0, 40):
            executor.submit(compete).result(timeout=10)
        with admission.slot(), admission.reserve(0, 75):
            pass


def test_a_failed_filesystem_observation_does_not_reserve_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filesystem error is propagated and leaves the next capacity check usable."""
    admission = CompletionAdmission(max_concurrent=1, reserve_bytes=25)

    def unavailable(_: int) -> os.statvfs_result:
        raise OSError(errno.EIO, "filesystem unavailable")

    monkeypatch.setattr(os, "fstatvfs", unavailable)
    with pytest.raises(OSError) as error, admission.slot(), admission.reserve(0, 75):
        pytest.fail("an unreadable filesystem admitted a copy")
    assert error.value.errno == errno.EIO
    _free_capacity(monkeypatch, 100)
    with admission.slot(), admission.reserve(0, 75):
        pass


def test_negative_expected_size_never_borrows_from_other_reservations() -> None:
    """Invalid file sizes are rejected before capacity accounting changes."""
    admission = CompletionAdmission(max_concurrent=1, reserve_bytes=0)
    with (
        pytest.raises(ValueError, match="size cannot be negative"),
        admission.slot(),
        admission.reserve(0, -1),
    ):
        pytest.fail("negative file size was admitted")


def test_real_filesystem_admission_allows_an_empty_file(tmp_path: Path) -> None:
    """A held real directory provides usable available-block capacity for completion."""
    admission = CompletionAdmission(max_concurrent=1, reserve_bytes=0)
    with directory(tmp_path) as descriptor, admission.slot(), admission.reserve(descriptor, 0):
        pass
