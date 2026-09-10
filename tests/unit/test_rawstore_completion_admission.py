"""Completion admission bounds copies while retaining capacity for other storage work."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from typing import TYPE_CHECKING

import pytest

from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rawstore import store as store_module
from huron.pkg.rawstore.completion import CompletionAdmission
from huron.pkg.rawstore.materialize import directory

if TYPE_CHECKING:
    from collections.abc import Iterator
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


@pytest.fixture
def staged_upload(tmp_path: Path) -> tuple[PosixRawStore, Path]:
    """Stage a real upload with a small explicit completion reserve."""
    store = PosixRawStore(tmp_path, completion_reserve_bytes=25)
    store.initialize()
    session = tmp_path / ".staging/session"
    store.create_staging(session)
    store.write_part(session, "input", [b"verified"], offset=0, length=8)
    return store, session


def _finish_upload(store: PosixRawStore, session: Path) -> tuple[int, str]:
    return store.finish_file(
        session,
        "input",
        "nested/file",
        expected_size=8,
        expected_sha256=hashlib.sha256(b"verified").hexdigest(),
    )


def test_store_refuses_capacity_without_creating_a_candidate_or_installing_payload(
    staged_upload: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Insufficient capacity preserves the upload and creates no completion or payload file."""
    store, session = staged_upload
    _free_capacity(monkeypatch, 32)
    with pytest.raises(OSError) as error:
        _finish_upload(store, session)
    assert error.value.errno == errno.ENOSPC
    assert (session / "upload/input").read_bytes() == b"verified"
    assert list((session / "completion").iterdir()) == []
    assert not (session / "envelope/payload/nested/file").exists()
    _free_capacity(monkeypatch, 33)
    assert _finish_upload(store, session) == (8, hashlib.sha256(b"verified").hexdigest())


def test_installed_replay_needs_neither_free_capacity_nor_an_upload_input(
    staged_upload: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed file replays its verified bytes even when a fresh copy would be refused."""
    store, session = staged_upload
    _free_capacity(monkeypatch, 33)
    completed = _finish_upload(store, session)
    installed = session / "envelope/payload/nested/file"
    original_inode = installed.stat().st_ino
    store.discard_file(session, "input")
    _free_capacity(monkeypatch, 0)
    assert _finish_upload(store, session) == completed
    assert installed.stat().st_ino == original_inode
    assert installed.read_bytes() == b"verified"
    assert list((session / "completion").iterdir()) == []


@pytest.mark.parametrize("failure", [OSError, asyncio.CancelledError])
def test_store_releases_admission_after_copy_failure_and_candidate_cleanup(
    staged_upload: tuple[PosixRawStore, Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
) -> None:
    """A failed candidate leaves no installation or leaked permit and a full retry succeeds."""
    store, session = staged_upload
    _free_capacity(monkeypatch, 33)

    def fail_write(_: int, __: bytes) -> int:
        raise failure()

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", fail_write)
        with pytest.raises(failure):
            _finish_upload(store, session)
    assert list((session / "completion").iterdir()) == []
    assert not (session / "envelope/payload/nested/file").exists()
    with ThreadPoolExecutor(max_workers=1) as executor:
        completed = executor.submit(_finish_upload, store, session).result(timeout=10)
    assert completed == (8, hashlib.sha256(b"verified").hexdigest())


def test_waiting_completion_rechecks_the_winner_before_reserving_capacity(
    staged_upload: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued retry reuses the winner after disk capacity drops below the copy reserve."""
    store, session = staged_upload
    _free_capacity(monkeypatch, 33)
    copying, release = Event(), Event()
    file_chunks = store_module.file_chunks

    def held_chunks(parent: int, name: str) -> Iterator[bytes]:
        for block in file_chunks(parent, name):
            copying.set()
            assert release.wait(10)
            yield block

    monkeypatch.setattr(store_module, "file_chunks", held_chunks)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_finish_upload, store, session)
        try:
            assert copying.wait(10)
            _free_capacity(monkeypatch, 0)
            second = executor.submit(_finish_upload, store, session)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.05)
        finally:
            release.set()
        assert first.result(timeout=10) == second.result(timeout=10)
    assert (session / "envelope/payload/nested/file").read_bytes() == b"verified"
    assert list((session / "completion").iterdir()) == []
