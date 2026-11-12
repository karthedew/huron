"""The local state: one atomic ``working.json`` per working copy, the state lock and the push lock.

The tests of kills and of two processes run real child processes (``tests.support.state_child``)
that stop at a named system call of the atomic write.
"""

import errno
import fcntl
import json
import os
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from huron.applications.cli.config import Config
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.localstate import (
    FORMAT,
    LOCK_WAIT,
    LocalState,
    PendingCommit,
    StagedAdd,
    Tokens,
    WorkingState,
    filesystem_type,
    state_root,
    write_atomically,
)
from tests.support.cli import Cli
from tests.support.clock import MonotonicClock
from tests.support.disk import snapshot
from tests.support.state_child import POINTS, Child, child_environment

#: The points of the atomic write before which the old file stays.
BEFORE_RENAME = frozenset({"before-file-sync", "after-file-sync", "before-rename"})
OLD_STAGE = {
    "adds": [{"rel_path": "a.txt", "source": "/data/a.txt", "size": 5, "copied": True}],
    "removes": [],
}
#: The hints of a state file that the CLI cannot read or save, by the cause.
PERMISSIONS_HINT = "correct the permissions. Then run the command again"
SPACE_HINT = "make free space. Then run the command again"
KIND_HINT = (
    "find the file or directory of the incorrect type in this path."
    " Move it to a different location. Then run the command again"
)
CAUSE_HINT = "correct the cause that the error message gives. Then run the command again"


@pytest.fixture
def state(tmp_path: Path) -> LocalState:
    return LocalState(tmp_path / "state" / "huron")


@pytest.fixture
def children() -> Iterator[Callable[..., Child]]:
    """Start children of ``tests.support.state_child``; none is left running after the test."""
    started: list[Child] = []

    def start(environ: dict[str, str], *args: str) -> Child:
        child = Child(environ, *args)
        started.append(child)
        return child

    yield start
    for child in started:
        if child.running():
            child.kill()
    assert not any(child.running() for child in started)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home for children: ``c-1`` is checked out at version 3 with ``a.txt`` staged."""
    root = tmp_path / "home"
    state = LocalState(state_root(child_environment(root)))
    state.check_out("c-1", "cat.ns.x", 3, "o/cat/ns/x")
    with state.changing("c-1") as working:
        working.adds = [StagedAdd("a.txt", "/data/a.txt", 5, 10, "ab" * 32)]
    Config(current_collection="c-1").save(root / "config" / "huron" / "config.yaml")
    for name in ("b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    return root


def full_state() -> WorkingState:
    """A working copy with a value in every field."""
    return WorkingState(
        "c-1",
        "cat.ns.x",
        "o/cat/ns/x",
        7,
        [StagedAdd("a.txt", "/data/a.txt", 5, 1_700_000_000_000_000_000, "ab" * 32, "t", "u", "r")],
        ["gone.txt"],
        PendingCommit("req-1", {"request_id": "req-1", "adds": [], "removes": ["gone.txt"]}),
    )


def written(state: LocalState, collection_id: str = "c-1") -> Path:
    return state.root / "collections" / collection_id / "working.json"


def staged_paths(state: LocalState, collection_id: str = "c-1") -> list[str]:
    working = state.working(collection_id)
    assert working is not None
    return [add.rel_path for add in working.adds]


def hold(path: Path) -> int:
    """Take ``path``'s flock from another open file, as another process would."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


# The working copy file.


def test_a_working_copy_round_trips_every_field_with_mode_0600(state: LocalState) -> None:
    state.check_out("c-1", "cat.ns.x", 7, "o/cat/ns/x")
    with state.changing("c-1") as working:
        full = full_state()
        working.adds, working.removes = full.adds, full.removes
        working.pending_commit = full.pending_commit
    assert state.working("c-1") == full_state()
    path = written(state)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    document = json.loads(path.read_text())
    assert document["format"] == FORMAT == 1
    assert sorted(document) == [
        "adds",
        "base_version",
        "collection_id",
        "format",
        "identifier",
        "path",
        "pending_commit",
        "removes",
    ]
    assert sorted(document["adds"][0]) == [
        "attempt_id",
        "attempt_state",
        "mtime_ns",
        "rel_path",
        "sha256",
        "size",
        "source",
        "upload_id",
    ]
    assert document["pending_commit"]["body"]["removes"] == ["gone.txt"]


def test_a_new_working_copy_has_an_empty_stage_and_no_pending_commit(state: LocalState) -> None:
    working = state.check_out("c-1", "cat.ns.x", 2, None)
    assert working == WorkingState("c-1", "cat.ns.x", None, 2)
    assert working.empty and working.pending_commit is None
    assert state.working("c-1") == working
    document = json.loads(written(state).read_text())
    assert (document["adds"], document["removes"], document["pending_commit"]) == ([], [], None)


def test_a_checkout_again_keeps_the_stage_and_takes_the_new_identity(state: LocalState) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    with state.changing("c-1") as working:
        working.removes = ["a.txt"]
    again = state.check_out("c-1", "cat.ns.renamed", 5, "o/cat/ns/renamed")
    assert again == WorkingState("c-1", "cat.ns.renamed", "o/cat/ns/renamed", 5, [], ["a.txt"])
    assert state.working("c-1") == again


def test_reading_a_missing_working_copy_gives_none_and_creates_nothing(
    state: LocalState,
) -> None:
    assert state.working("c-1") is None
    assert state.working_copies() == []
    assert state.read_draft("c-1") is None
    assert not state.root.exists()


def test_working_copies_are_listed_by_identifier_and_a_draft_alone_is_no_copy(
    state: LocalState,
) -> None:
    later = state.check_out("id-1", "zeta.ns.b", 1, None)
    earlier = state.check_out("id-2", "alpha.ns.a", 5, "p")
    state.write_draft("id-3", {"title": "x"})
    with state.push_lock("id-4"):
        pass
    assert state.working_copies() == [earlier, later]


def test_a_change_is_written_when_its_block_ends(state: LocalState) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    with state.changing("c-1") as working:
        working.adds.append(StagedAdd("a.txt", "/data/a.txt", 5, 10, "ab" * 32))
        assert staged_paths(state) == []
    assert staged_paths(state) == ["a.txt"]


def test_a_change_that_raises_writes_nothing(state: LocalState) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    before = written(state).read_bytes()
    with pytest.raises(UsageError), state.changing("c-1") as working:
        working.removes.append("a.txt")
        raise UsageError("stop")
    assert written(state).read_bytes() == before


def test_a_change_of_a_collection_without_a_working_copy_is_refused(state: LocalState) -> None:
    with pytest.raises(UsageError) as raised, state.changing("c-9"):
        pytest.fail("the block must not run")
    assert raised.value.message == "there is no working copy of the collection c-9"
    assert raised.value.hint == "run `huron checkout <identifier>`"


def test_the_same_file_means_the_same_path_source_size_modification_time_and_hash() -> None:
    add = StagedAdd("a.txt", "/data/a.txt", 5, 10, "a" * 64, attempt_id="t")
    assert add.same_file(StagedAdd("a.txt", "/data/a.txt", 5, 10, "a" * 64, upload_id="u"))
    assert not add.same_file(StagedAdd("b.txt", "/data/a.txt", 5, 10, "a" * 64))
    assert not add.same_file(StagedAdd("a.txt", "/data/b.txt", 5, 10, "a" * 64))
    assert not add.same_file(StagedAdd("a.txt", "/data/a.txt", 6, 10, "a" * 64))
    assert not add.same_file(StagedAdd("a.txt", "/data/a.txt", 5, 11, "a" * 64))
    assert not add.same_file(StagedAdd("a.txt", "/data/a.txt", 5, 10, "b" * 64))


# Refused files.


def test_a_working_copy_in_the_old_format_is_refused_and_not_changed(state: LocalState) -> None:
    directory = state.root / "collections" / "c-1"
    directory.mkdir(parents=True)
    (directory / "copy.json").write_text('{"collection_id": "c-1", "version": 2}')
    (directory / "stage.json").write_text(json.dumps(OLD_STAGE))
    before = snapshot(directory)
    for read in (lambda: state.working("c-1"), state.working_copies):
        with pytest.raises(CliError) as raised:
            read()
        assert raised.value.exit_code == ExitCode.FAILED
        assert raised.value.message == (
            f"{directory} holds a working copy in an old format. This CLI cannot read it"
        )
        assert raised.value.hint == (
            f"the CLI did not change the files in {directory}. Move the directory to a"
            " different location. Then run `huron checkout <identifier>` again"
        )
    with pytest.raises(CliError):
        state.check_out("c-1", "cat.ns.x", 3, None)
    assert snapshot(directory) == before


def test_an_old_stage_file_alone_is_refused(state: LocalState) -> None:
    directory = state.root / "collections" / "c-1"
    directory.mkdir(parents=True)
    (directory / "stage.json").write_text(json.dumps(OLD_STAGE))
    with pytest.raises(CliError, match="old format"):
        state.working("c-1")


NOT_VALID = "a format version that is not valid"
#: A complete working copy file of the collection ``c-2``.
OTHER_COLLECTION = {
    "format": 1,
    "collection_id": "c-2",
    "identifier": "cat.ns.x",
    "path": None,
    "base_version": 3,
    "adds": [],
    "removes": ["a.txt"],
    "pending_commit": None,
}


@pytest.mark.parametrize(
    ("version", "has"),
    [
        (2, "the format version 2"),
        (0, "the format version 0"),
        (-(10**18), f"the format version {-(10**18)}"),
        (10**20, NOT_VALID),
        ("1", 'the format version "1"'),
        ("v" * 18, f'the format version "{"v" * 18}"'),
        ("v" * 19, NOT_VALID),
        (True, NOT_VALID),
        (1.0, NOT_VALID),
        (None, NOT_VALID),
        ([1], NOT_VALID),
        ({"major": 1, "notes": ["x" * 1000] * 100}, NOT_VALID),
    ],
)
def test_an_unknown_format_version_is_refused_and_not_changed(
    state: LocalState, version: object, has: str
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    document = json.loads(written(state).read_text())
    written(state).write_text(json.dumps({**document, "format": version}))
    before = snapshot(written(state).parent)
    with pytest.raises(CliError) as raised:
        state.working("c-1")
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == (
        f"{written(state)} has {has}. This CLI can read only the format version 1"
    )
    assert "Move the directory to a different location" in str(raised.value.hint)
    with pytest.raises(CliError), state.changing("c-1"):
        pytest.fail("the block must not run")
    assert snapshot(written(state).parent) == before


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{not json",
        "[1]",
        '{"collection_id": "c-1"}',
        json.dumps({"format": 1}),
        json.dumps({"format": 1, "collection_id": "c-1", "identifier": "x", "path": None}),
        json.dumps(
            {
                "format": 1,
                "collection_id": "c-1",
                "identifier": "x",
                "path": None,
                "base_version": "3",
            }
        ),
        json.dumps(
            {
                "format": 1,
                "collection_id": "c-1",
                "identifier": "x",
                "path": None,
                "base_version": 3,
                "unknown": 1,
            }
        ),
        json.dumps(
            {
                "format": 1,
                "collection_id": "c-1",
                "identifier": "x",
                "path": None,
                "base_version": 3,
                "adds": [{"rel_path": "a", "source": "/a", "size": 1, "copied": True}],
            }
        ),
        json.dumps(
            {
                "format": 1,
                "collection_id": "c-1",
                "identifier": "x",
                "path": None,
                "base_version": 3,
                "adds": [
                    {"rel_path": "a", "source": "/a", "size": 1, "mtime_ns": None, "sha256": None}
                ],
            }
        ),
        json.dumps(OTHER_COLLECTION),
    ],
    ids=[
        "empty",
        "broken",
        "list",
        "no version",
        "no fields",
        "no base version",
        "base version as text",
        "unknown key",
        "unknown add key",
        "add without its modification time and hash",
        "another collection",
    ],
)
def test_a_file_that_is_not_a_working_copy_is_refused_and_not_changed(
    state: LocalState, content: str
) -> None:
    written(state).parent.mkdir(parents=True)
    written(state).write_text(content)
    with pytest.raises(CliError) as raised:
        state.working("c-1")
    assert raised.value.message == f"{written(state)} is not a valid working copy file"
    assert raised.value.exit_code == ExitCode.FAILED
    assert written(state).read_text() == content


def test_a_working_copy_file_of_another_collection_gives_no_path_and_is_not_changed(
    state: LocalState,
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    written(state).write_text(json.dumps(OTHER_COLLECTION))
    before = snapshot(state.root)
    for use in (
        lambda: state.working("c-1"),
        state.working_copies,
        lambda: state.check_out("c-1", "cat.ns.x", 3, None),
        lambda: state.changing("c-1").__enter__(),
    ):
        with pytest.raises(CliError) as raised:
            use()
        assert raised.value.exit_code == ExitCode.FAILED
        assert raised.value.message == f"{written(state)} is not a valid working copy file"
        assert "Move the directory to a different location" in str(raised.value.hint)
    assert snapshot(state.root) == before
    assert not (state.root / "collections" / "c-2").exists()


@pytest.mark.parametrize(
    "collection_id", ["", ".", "..", "../c-1", "c-1/..", "a/b", "/tmp/x", "a\0b"]
)
@pytest.mark.parametrize(
    "use",
    [
        lambda state, collection_id: state.working(collection_id),
        lambda state, collection_id: state.check_out(collection_id, "cat.ns.x", 2, None),
        lambda state, collection_id: state.changing(collection_id).__enter__(),
        lambda state, collection_id: state.push_lock(collection_id).__enter__(),
        lambda state, collection_id: state.read_draft(collection_id),
        lambda state, collection_id: state.write_draft(collection_id, {"title": "x"}),
        lambda state, collection_id: state.delete_draft(collection_id),
    ],
    ids=["working", "checkout", "change", "push lock", "read draft", "write draft", "delete draft"],
)
def test_a_collection_id_that_is_not_a_name_in_collections_is_refused(
    tmp_path: Path, collection_id: str, use: Callable[[LocalState, str], object]
) -> None:
    state = LocalState(tmp_path / "state" / "huron")
    with pytest.raises(CliError) as raised:
        use(state, collection_id)
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == f"{json.dumps(collection_id)} is not a valid collection ID"
    assert raised.value.hint == "run `huron checkout <identifier>`"
    made = {str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")}
    assert made <= {"state", "state/huron", "state/huron/state.lock"}


# The atomic write.


def test_an_atomic_write_syncs_the_file_renames_it_then_syncs_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.json"
    target.write_text("old")
    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(descriptor: int) -> None:
        kind = "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
        calls.append(f"sync {kind}")
        real_fsync(descriptor)

    def replace(source: Any, destination: Any) -> None:
        calls.append(f"rename {Path(source).parent == tmp_path} {Path(destination).name}")
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    write_atomically(target, b"new")
    monkeypatch.undo()
    assert calls == ["sync file", "rename True f.json", "sync directory"]
    assert target.read_bytes() == b"new"
    assert [path.name for path in tmp_path.iterdir()] == ["f.json"]


def test_an_atomic_write_gives_mode_0600_whatever_the_umask(tmp_path: Path) -> None:
    previous = os.umask(0)
    try:
        write_atomically(tmp_path / "f.json", b"x" * 100_000)
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "f.json").stat().st_mode) == 0o600
    assert (tmp_path / "f.json").read_bytes() == b"x" * 100_000


@pytest.mark.parametrize("call", ["write", "fsync"])
def test_a_full_disk_keeps_the_old_file_and_removes_the_temporary_file(
    state: LocalState, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    before = snapshot(written(state).parent)

    def full(*args: object) -> int:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(os, call, full)
    with pytest.raises(CliError) as raised, state.changing("c-1") as working:
        working.removes.append("a.txt")
    monkeypatch.undo()
    assert raised.value.message == f"the CLI cannot save {written(state)}: No space left on device"
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.hint == SPACE_HINT
    assert snapshot(written(state).parent) == before
    assert state.working("c-1") == WorkingState("c-1", "cat.ns.x", None, 2)


@pytest.mark.parametrize("point", POINTS)
def test_a_kill_during_a_write_leaves_the_complete_old_or_new_file(
    home: Path, tmp_path: Path, children: Callable[..., Child], point: str
) -> None:
    environ = child_environment(home)
    state = LocalState(state_root(environ), lock_wait=5.0)
    child = children(environ, "huron", "--pause", point, "add", str(tmp_path / "b.txt"))
    child.expect("paused")
    child.kill()
    expected = ["a.txt"] if point in BEFORE_RENAME else ["a.txt", "b.txt"]
    assert staged_paths(state) == expected
    with state.changing("c-1") as working:
        working.removes.append("gone.txt")
    assert staged_paths(state) == expected


# The state lock.


def test_two_processes_that_change_the_stage_give_two_changes(
    home: Path, tmp_path: Path, children: Callable[..., Child]
) -> None:
    environ = child_environment(home)
    first = children(environ, "huron", "--pause", "before-rename", "add", str(tmp_path / "b.txt"))
    first.expect("paused")
    second = children(environ, "huron", "--report-wait", "add", str(tmp_path / "c.txt"))
    second.expect("waiting")
    assert second.running()
    first.resume()
    assert first.finish() == 0
    assert second.finish() == 0
    assert staged_paths(LocalState(state_root(environ))) == ["a.txt", "b.txt", "c.txt"]


def test_the_state_lock_waits_for_the_holder_then_fails_with_exit_code_6(
    state: LocalState,
) -> None:
    clock = MonotonicClock()
    waiting = LocalState(state.root, clock=clock, sleep=clock.sleep)
    state.root.mkdir(parents=True)
    holder = hold(state.root / "state.lock")
    try:
        with pytest.raises(CliError) as raised, waiting.locked():
            pytest.fail("the lock must not be taken")
    finally:
        os.close(holder)
    assert raised.value.exit_code == ExitCode.CONFLICT == 6
    assert raised.value.message == (
        f"another huron command holds the lock of {state.root} for more than 10 seconds"
    )
    assert raised.value.hint == "wait for the other command to stop. Then run the command again"
    assert sum(clock.slept) == pytest.approx(LOCK_WAIT) and max(clock.slept) <= 0.05


def test_the_state_lock_is_taken_when_the_holder_releases_it_in_time(state: LocalState) -> None:
    clock = MonotonicClock()
    waiting = LocalState(state.root, clock=clock, sleep=clock.sleep)
    state.root.mkdir(parents=True)
    holder = hold(state.root / "state.lock")

    def release() -> None:
        if len(clock.slept) == 3:
            os.close(holder)

    clock.on_sleep = release
    with waiting.locked():
        assert len(clock.slept) == 3


def test_the_state_lock_of_another_process_is_waited_for(
    state: LocalState, children: Callable[..., Child]
) -> None:
    environ = child_environment(state.root.parent.parent)
    holder = children(environ, "hold-state", str(state.root))
    holder.expect("held")
    with pytest.raises(CliError) as raised, LocalState(state.root, lock_wait=0.2).locked():
        pytest.fail("the lock must not be taken")
    assert raised.value.exit_code == ExitCode.CONFLICT
    holder.resume()
    assert holder.finish() == 0
    with LocalState(state.root, lock_wait=0.2).locked():
        pass


def test_the_kernel_releases_the_locks_of_a_killed_process(
    state: LocalState, children: Callable[..., Child]
) -> None:
    environ = child_environment(state.root.parent.parent)
    for args in (["hold-state", str(state.root)], ["hold-push", str(state.root), "c-1"]):
        holder = children(environ, *args)
        holder.expect("held")
        holder.kill()
    with LocalState(state.root, lock_wait=0.2).locked(), state.push_lock("c-1"):
        assert (state.root / "state.lock").exists()


def test_a_nested_use_of_the_state_lock_in_one_process_does_not_wait(state: LocalState) -> None:
    clock = MonotonicClock()
    nested = LocalState(state.root, clock=clock, sleep=clock.sleep)
    with nested.locked():
        with nested.locked():
            nested.check_out("c-1", "cat.ns.x", 2, None)
        nested.write_tokens(Tokens("t", 1.0, "dave"))
    assert clock.slept == []
    with LocalState(state.root, lock_wait=0.0).locked():
        pass


def test_the_lock_files_keep_their_inode_across_cycles_and_processes(
    state: LocalState, children: Callable[..., Child]
) -> None:
    with state.locked(), state.push_lock("c-1"):
        pass
    lock = state.root / "state.lock"
    push = state.root / "collections" / "c-1" / "push.lock"
    inodes = (lock.stat().st_ino, push.stat().st_ino)
    for _ in range(100):
        with state.locked(), state.push_lock("c-1"):
            pass
    environ = child_environment(state.root.parent.parent)
    for args in (["hold-state", str(state.root)], ["hold-push", str(state.root), "c-1"]):
        holder = children(environ, *args)
        holder.expect("held")
        holder.resume()
        assert holder.finish() == 0
    assert (lock.stat().st_ino, push.stat().st_ino) == inodes
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


# The push lock.


def test_a_second_push_of_the_same_working_copy_fails_at_once(
    state: LocalState, children: Callable[..., Child]
) -> None:
    environ = child_environment(state.root.parent.parent)
    holder = children(environ, "hold-push", str(state.root), "c-1")
    holder.expect("held")
    started = time.monotonic()
    with pytest.raises(CliError) as raised, state.push_lock("c-1"):
        pytest.fail("the lock must not be taken")
    assert time.monotonic() - started < 1.0
    assert raised.value.exit_code == ExitCode.CONFLICT
    assert raised.value.message == "another `huron push` of this working copy holds the push lock"
    assert raised.value.hint == "wait for that push to stop. Then run `huron push` again"
    with state.push_lock("c-2"), state.locked():
        pass
    holder.resume()
    assert holder.finish() == 0
    with state.push_lock("c-1"):
        pass


# The file system check.


def test_a_state_root_on_nfs_is_refused_before_the_first_lock(tmp_path: Path) -> None:
    root = tmp_path / "state" / "huron"
    asked: list[Path] = []

    def nfs(path: Path) -> str:
        asked.append(path)
        return "nfs4"

    state = LocalState(root, filesystem=nfs)
    for take in (state.locked, lambda: state.push_lock("c-1")):
        with pytest.raises(CliError) as raised, take():
            pytest.fail("the lock must not be taken")
        assert raised.value.exit_code == ExitCode.FAILED
        assert raised.value.message == (
            f"the state directory {root} is on NFS. The CLI needs a local file system for its locks"
        )
        assert raised.value.hint == (
            "set `XDG_STATE_HOME` to a directory on a local disk of this machine"
        )
    assert asked == [root, root]
    assert list(root.iterdir()) == []


def test_a_local_state_root_is_checked_once(tmp_path: Path) -> None:
    asked: list[Path] = []

    def local(path: Path) -> str:
        asked.append(path)
        return "ext4"

    state = LocalState(tmp_path / "state", filesystem=local)
    state.check_out("c-1", "cat.ns.x", 2, None)
    with state.push_lock("c-1"), state.locked():
        pass
    assert asked == [tmp_path / "state"]


def test_the_file_system_type_on_linux_comes_from_the_device_in_mountinfo(
    tmp_path: Path,
) -> None:
    device = os.stat(tmp_path).st_dev
    here = f"{os.major(device)}:{os.minor(device)}"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
        "short line\n"
        f"40 22 {here} / /data rw,relatime shared:5 master:2 - nfs4 lake:/export rw,vers=4.2\n"
    )
    assert filesystem_type(tmp_path, mountinfo=mountinfo) == "nfs4"
    mountinfo.write_text("22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n")
    assert filesystem_type(tmp_path, mountinfo=mountinfo) == ""
    assert filesystem_type(tmp_path) != ""


def test_the_file_system_type_without_mountinfo_comes_from_the_mount_listing(
    tmp_path: Path,
) -> None:
    listing = (
        "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
        "map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)\n"
        "lake:/export on /Volumes/lake (nfs, nodev, nosuid, mounted by karl)\n"
        "something unexpected\n"
    )
    ran: list[list[str]] = []

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, listing, "")

    missing = tmp_path / "no-mountinfo"
    assert filesystem_type(Path("/Volumes/lake/k/s"), mountinfo=missing, run=run) == "nfs"
    assert filesystem_type(Path("/Users/k/.local"), mountinfo=missing, run=run) == "apfs"
    assert ran == [["/sbin/mount"], ["/sbin/mount"]]

    def nothing(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "")

    assert filesystem_type(tmp_path, mountinfo=missing, run=nothing) == ""


def test_the_file_system_type_without_mountinfo_reads_a_linux_mount_listing(
    tmp_path: Path,
) -> None:
    listing = (
        "/dev/sda1 on / type ext4 (rw,relatime)\n"
        "lake:/export on /data type nfs4 (rw,relatime,vers=4.2)\n"
        "/dev/sdb1 on /data/scratch type xfs (rw)\n"
    )

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, listing, "")

    missing = tmp_path / "no-mountinfo"
    assert filesystem_type(Path("/data/lake/k"), mountinfo=missing, run=run) == "nfs4"
    assert filesystem_type(Path("/data/scratch/k"), mountinfo=missing, run=run) == "xfs"
    assert filesystem_type(Path("/home/k/.local"), mountinfo=missing, run=run) == "ext4"


def test_the_file_system_type_is_unknown_without_mountinfo_and_without_mount(
    tmp_path: Path,
) -> None:
    def absent(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), command[0])

    missing = tmp_path / "no-mountinfo"
    assert filesystem_type(tmp_path, mountinfo=missing, run=absent) == ""
    unknown = partial(filesystem_type, mountinfo=missing, run=absent)
    state = LocalState(tmp_path / "state", filesystem=unknown)
    state.check_out("c-1", "cat.ns.x", 2, None)
    assert state.working("c-1") == WorkingState("c-1", "cat.ns.x", None, 2)


# Tokens, drafts and the state root.


def test_tokens_round_trip_and_are_refused_when_others_can_read_them(state: LocalState) -> None:
    assert state.read_tokens() is None and state.delete_tokens() is False
    state.write_tokens(Tokens("t", 1.0, "dave", None))
    assert state.read_tokens() == Tokens("t", 1.0, "dave", None)
    path = state.root / "tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    os.chmod(path, 0o644)
    with pytest.raises(CliError) as raised:
        state.read_tokens()
    assert raised.value.exit_code == ExitCode.NOT_LOGGED_IN
    assert state.delete_tokens() is True and not path.exists()


def test_drafts_round_trip_and_are_deleted(state: LocalState) -> None:
    state.write_draft("c-1", {"title": "x"})
    assert state.read_draft("c-1") == {"title": "x"}
    path = state.root / "collections" / "c-1" / "metadata.draft.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    state.delete_draft("c-1")
    state.delete_draft("c-1")
    assert state.read_draft("c-1") is None


@pytest.mark.parametrize(
    "change",
    [
        lambda state: state.write_tokens(Tokens("t", 2.0, "dave")),
        lambda state: state.delete_tokens(),
        lambda state: state.write_draft("c-1", {"title": "y"}),
        lambda state: state.delete_draft("c-1"),
    ],
    ids=["write tokens", "delete tokens", "write draft", "delete draft"],
)
def test_token_and_draft_changes_wait_for_the_state_lock(
    state: LocalState, change: Callable[[LocalState], object]
) -> None:
    state.write_tokens(Tokens("t", 1.0, "erin"))
    state.write_draft("c-1", {"title": "x"})
    before = snapshot(state.root)
    holder = hold(state.root / "state.lock")
    try:
        with pytest.raises(CliError) as raised:
            change(LocalState(state.root, lock_wait=0.0))
    finally:
        os.close(holder)
    assert raised.value.exit_code == ExitCode.CONFLICT
    assert snapshot(state.root) == before
    change(LocalState(state.root, lock_wait=0.0))
    assert snapshot(state.root) != before


def test_the_state_root_follows_xdg_state_home_then_home() -> None:
    assert state_root({"XDG_STATE_HOME": "/s"}) == Path("/s/huron")
    assert state_root({"XDG_STATE_HOME": "", "HOME": "/h"}) == Path("/h/.local/state/huron")


def test_a_saved_configuration_is_written_atomically_under_the_state_lock(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken: list[bool] = []
    real = Config.save

    def save(config: Config, path: Path) -> None:
        probe = LocalState(cli.state.root, lock_wait=0.0)
        try:
            with probe.locked():
                taken.append(False)
        except CliError:
            taken.append(True)
        real(config, path)

    monkeypatch.setattr(Config, "save", save)
    cli.ok("config", "set", "mount_prefix", "/mnt/share")
    assert taken == [True]
    assert stat.S_IMODE(cli.config_path.stat().st_mode) == 0o600
    assert [path.name for path in cli.config_path.parent.iterdir()] == ["config.yaml"]


# State directories and state that the CLI cannot use.

ROOT_ONLY = ("huron",)
COPY_DIRECTORIES = ("huron", "huron/collections", "huron/collections/c-1")


def take_state_lock(state: LocalState) -> None:
    with state.locked():
        pass


def take_push_lock(state: LocalState) -> None:
    with state.push_lock("c-1"):
        pass


CHANGES: list[Callable[[LocalState], object]] = [
    lambda state: state.check_out("c-1", "cat.ns.x", 2, None),
    lambda state: state.write_tokens(Tokens("t", 1.0, "dave")),
    lambda state: state.write_draft("c-1", {"title": "x"}),
    take_state_lock,
    take_push_lock,
]
CHANGE_IDS = ["checkout", "write tokens", "write draft", "state lock", "push lock"]
#: The state directories that each of :data:`CHANGES` makes on a fresh state root.
MADE = [COPY_DIRECTORIES, ROOT_ONLY, COPY_DIRECTORIES, ROOT_ONLY, COPY_DIRECTORIES]


def directory_modes(state: LocalState) -> dict[str, int]:
    """The mode of the state root and of each directory below it, by path from its parent."""
    directories = [state.root, *(path for path in state.root.rglob("*") if path.is_dir())]
    return {
        str(path.relative_to(state.root.parent)): stat.S_IMODE(path.stat().st_mode)
        for path in directories
    }


@pytest.mark.parametrize("mask", [0o002, 0o027, 0o077, 0o277], ids=lambda mask: f"umask {mask:03o}")
@pytest.mark.parametrize(("change", "made"), list(zip(CHANGES, MADE, strict=True)), ids=CHANGE_IDS)
def test_each_state_directory_that_the_cli_creates_gets_mode_0700_whatever_the_umask(
    tmp_path: Path, change: Callable[[LocalState], object], made: tuple[str, ...], mask: int
) -> None:
    state = LocalState(tmp_path / "huron")
    os.umask(mask)
    change(state)
    assert directory_modes(state) == dict.fromkeys(made, 0o700)


def test_missing_parents_of_the_state_root_get_the_default_mode(state: LocalState) -> None:
    os.umask(0o002)
    state.check_out("c-1", "cat.ns.x", 2, None)
    assert stat.S_IMODE(state.root.parent.stat().st_mode) == 0o775
    assert directory_modes(state) == dict.fromkeys(COPY_DIRECTORIES, 0o700)


def test_an_existing_state_directory_keeps_its_mode(state: LocalState) -> None:
    modes = {"huron": 0o750, "huron/collections": 0o755, "huron/collections/c-1": 0o711}
    state.root.parent.mkdir()
    for name, mode in modes.items():
        directory = state.root.parent / name
        directory.mkdir()
        directory.chmod(mode)
    os.umask(0o002)
    state.check_out("c-1", "cat.ns.x", 2, None)
    state.write_draft("c-1", {"title": "x"})
    state.write_tokens(Tokens("t", 1.0, "dave"))
    take_push_lock(state)
    assert directory_modes(state) == modes


def refused_save(change: Callable[[LocalState], object], state: LocalState, hint: str) -> CliError:
    with pytest.raises(CliError) as raised:
        change(state)
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.hint == hint
    return raised.value


@pytest.mark.parametrize("change", CHANGES, ids=CHANGE_IDS)
def test_a_state_root_below_a_file_is_refused(
    tmp_path: Path, change: Callable[[LocalState], object]
) -> None:
    (tmp_path / "file").write_text("keep")
    state = LocalState(state_root({"XDG_STATE_HOME": str(tmp_path / "file")}))
    refused = refused_save(change, state, KIND_HINT)
    assert refused.message == f"the CLI cannot save {state.root}: Not a directory"
    assert (tmp_path / "file").read_text() == "keep"


def test_a_state_root_below_a_file_holds_nothing_to_read(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("keep")
    state = LocalState(tmp_path / "file" / "huron")
    assert state.working("c-1") is None and state.working_copies() == []
    assert state.read_tokens() is None and state.read_draft("c-1") is None
    assert (tmp_path / "file").read_text() == "keep"


@pytest.mark.parametrize("change", CHANGES, ids=CHANGE_IDS)
def test_a_state_root_that_is_a_file_is_refused(
    state: LocalState, change: Callable[[LocalState], object]
) -> None:
    state.root.parent.mkdir()
    state.root.write_text("keep")
    refused = refused_save(change, state, KIND_HINT)
    assert refused.message == f"the CLI cannot save {state.root}: Not a directory"
    assert state.root.read_text() == "keep"


@pytest.mark.parametrize(
    "change", [CHANGES[0], CHANGES[2], take_push_lock], ids=["checkout", "write draft", "push lock"]
)
def test_a_collections_directory_that_is_a_file_is_refused(
    state: LocalState, change: Callable[[LocalState], object]
) -> None:
    state.write_tokens(Tokens("t", 1.0, "dave"))
    (state.root / "collections").write_text("keep")
    refused = refused_save(change, state, KIND_HINT)
    assert refused.message == f"the CLI cannot save {state.root / 'collections'}: Not a directory"


@pytest.mark.parametrize("code", [errno.EACCES, errno.EROFS])
@pytest.mark.parametrize("change", CHANGES, ids=CHANGE_IDS)
def test_a_state_root_that_cannot_be_created_is_refused(
    state: LocalState,
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[LocalState], object],
    code: int,
) -> None:
    real = os.mkdir

    def mkdir(path: Any, mode: int = 0o777) -> None:
        if Path(path) == state.root:
            raise OSError(code, os.strerror(code), str(path))
        real(path, mode)

    monkeypatch.setattr(os, "mkdir", mkdir)
    refused = refused_save(change, state, PERMISSIONS_HINT)
    assert refused.message == f"the CLI cannot save {state.root}: {os.strerror(code)}"
    assert not state.root.exists()


@pytest.mark.parametrize("code", [errno.EACCES, errno.EROFS])
@pytest.mark.parametrize(
    ("take", "lock"),
    [(take_state_lock, "state.lock"), (take_push_lock, "collections/c-1/push.lock")],
    ids=["state lock", "push lock"],
)
def test_a_lock_file_that_cannot_be_opened_is_refused(
    state: LocalState,
    monkeypatch: pytest.MonkeyPatch,
    take: Callable[[LocalState], None],
    lock: str,
    code: int,
) -> None:
    real = os.open

    def open_file(path: Any, flags: int, mode: int = 0o777) -> int:
        if str(path).endswith(".lock"):
            raise OSError(code, os.strerror(code), str(path))
        return real(path, flags, mode)

    monkeypatch.setattr(os, "open", open_file)
    refused = refused_save(take, state, PERMISSIONS_HINT)
    assert refused.message == f"the CLI cannot save {state.root / lock}: {os.strerror(code)}"
    assert not (state.root / lock).exists()


def deny_reading(monkeypatch: pytest.MonkeyPatch, denied: Path, code: int = errno.EACCES) -> None:
    """Make ``denied`` fail to read with the error number ``code``.

    The default, ``EACCES``, is what a file with mode 000 gives its user.
    """
    real = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == denied:
            raise OSError(code, os.strerror(code), str(path))
        return real(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)


@pytest.mark.parametrize(
    ("name", "read"),
    [
        ("collections/c-1/working.json", lambda state: state.working("c-1")),
        ("collections/c-1/working.json", lambda state: state.working_copies()),
        ("collections/c-1/metadata.draft.json", lambda state: state.read_draft("c-1")),
        ("tokens.json", lambda state: state.read_tokens()),
    ],
    ids=["working copy", "working copies", "draft", "tokens"],
)
def test_a_state_file_that_cannot_be_read_is_refused_and_not_changed(
    state: LocalState,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    read: Callable[[LocalState], object],
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    state.write_draft("c-1", {"title": "x"})
    state.write_tokens(Tokens("t", 1.0, "dave"))
    before = snapshot(state.root)
    with monkeypatch.context() as patch, pytest.raises(CliError) as raised:
        deny_reading(patch, state.root / name)
        read(state)
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == f"the CLI cannot read {state.root / name}: Permission denied"
    assert raised.value.hint == PERMISSIONS_HINT
    assert snapshot(state.root) == before


def test_a_collections_directory_that_cannot_be_listed_is_refused(
    state: LocalState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    base = state.root / "collections"
    real = os.listdir

    def listdir(path: Any) -> list[str]:
        if Path(path) == base:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return real(path)

    with monkeypatch.context() as patch, pytest.raises(CliError) as raised:
        patch.setattr(os, "listdir", listdir)
        state.working_copies()
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == f"the CLI cannot read {base}: Permission denied"
    assert raised.value.hint == PERMISSIONS_HINT


def test_a_working_copy_directory_that_cannot_be_searched_is_refused(
    state: LocalState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    directory = written(state).parent
    real = os.stat

    def search(path: Any, *args: Any, **options: Any) -> os.stat_result:
        if Path(path).parent == directory:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return real(path, *args, **options)

    for read in (lambda: state.working("c-1"), state.working_copies):
        with monkeypatch.context() as patch, pytest.raises(CliError) as raised:
            patch.setattr(os, "stat", search)
            read()
        assert raised.value.exit_code == ExitCode.FAILED
        assert raised.value.message == (
            f"the CLI cannot read {directory / 'copy.json'}: Permission denied"
        )
        assert raised.value.hint == PERMISSIONS_HINT


#: Error numbers of each cause, and the hint that each one gives.
ERRNO_HINTS = [
    (errno.EACCES, PERMISSIONS_HINT),
    (errno.EPERM, PERMISSIONS_HINT),
    (errno.EROFS, PERMISSIONS_HINT),
    (errno.ENOSPC, SPACE_HINT),
    (errno.EDQUOT, SPACE_HINT),
    (errno.ENOTDIR, KIND_HINT),
    (errno.EISDIR, KIND_HINT),
    (errno.EEXIST, KIND_HINT),
    (errno.EIO, CAUSE_HINT),
    (errno.ELOOP, CAUSE_HINT),
]
ERRNO_IDS = [errno.errorcode[code] for code, _ in ERRNO_HINTS]


@pytest.mark.parametrize(
    ("code", "hint"),
    # A read that gives ENOTDIR finds no file, so it is not an error.
    [(code, hint) for code, hint in ERRNO_HINTS if code != errno.ENOTDIR],
    ids=[name for name in ERRNO_IDS if name != "ENOTDIR"],
)
def test_a_state_file_that_cannot_be_read_gives_the_hint_of_the_cause(
    state: LocalState, monkeypatch: pytest.MonkeyPatch, code: int, hint: str
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)
    with monkeypatch.context() as patch, pytest.raises(CliError) as raised:
        deny_reading(patch, written(state), code)
        state.working("c-1")
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == f"the CLI cannot read {written(state)}: {os.strerror(code)}"
    assert raised.value.hint == hint


@pytest.mark.parametrize(("code", "hint"), ERRNO_HINTS, ids=ERRNO_IDS)
def test_a_state_file_that_cannot_be_saved_gives_the_hint_of_the_cause(
    state: LocalState, monkeypatch: pytest.MonkeyPatch, code: int, hint: str
) -> None:
    state.check_out("c-1", "cat.ns.x", 2, None)

    def refuse(*args: object) -> int:
        raise OSError(code, os.strerror(code))

    with monkeypatch.context() as patch, pytest.raises(CliError) as raised:
        patch.setattr(os, "write", refuse)
        with state.changing("c-1") as working:
            working.removes.append("a.txt")
    assert raised.value.exit_code == ExitCode.FAILED
    assert raised.value.message == f"the CLI cannot save {written(state)}: {os.strerror(code)}"
    assert raised.value.hint == hint


def test_a_listing_of_collections_skips_files_and_a_state_root_without_collections(
    state: LocalState,
) -> None:
    assert state.working_copies() == []
    copy = state.check_out("c-1", "cat.ns.x", 2, None)
    (state.root / "collections" / "stray").write_text("keep")
    assert state.working_copies() == [copy]


# Commands.


def test_commands_refuse_an_old_working_copy_and_leave_its_files(
    ready: Cli, tmp_path: Path
) -> None:
    directory = written(ready.state, ready.config_current()).parent
    written(ready.state, ready.config_current()).unlink()
    (directory / "copy.json").write_text('{"collection_id": "x", "version": 3}')
    (directory / "stage.json").write_text(json.dumps(OLD_STAGE))
    before = snapshot(directory)
    source = tmp_path / "b.txt"
    source.write_text("b")
    for argv in (
        ("status",),
        ("status", "--all"),
        ("add", str(source)),
        ("rm", "a.txt"),
        ("push",),
        ("checkout", "solar-wind.run7"),
    ):
        refused = ready.run(*argv)
        assert refused.exit_code == 1, argv
        assert "holds a working copy in an old format" in refused.stderr
        assert "unexpected" not in refused.stderr
    assert snapshot(directory) == before


def test_commands_refuse_a_working_copy_of_a_newer_format(ready: Cli, tmp_path: Path) -> None:
    path = written(ready.state, ready.config_current())
    path.write_text(json.dumps({**json.loads(path.read_text()), "format": 2}))
    before = path.read_bytes()
    source = tmp_path / "b.txt"
    source.write_text("b")
    for argv in (("status",), ("add", str(source)), ("checkout", "solar-wind.run7")):
        refused = ready.run(*argv)
        assert refused.exit_code == 1, argv
        assert "has the format version 2" in refused.stderr
    assert path.read_bytes() == before


def test_a_command_fails_with_exit_code_6_when_another_holds_the_state_lock(
    ready: Cli, tmp_path: Path
) -> None:
    clock = MonotonicClock()
    ready.state = LocalState(ready.state.root, clock=clock, sleep=clock.sleep)
    holder = hold(ready.state.root / "state.lock")
    source = tmp_path / "b.txt"
    source.write_text("b")
    try:
        refused = ready.run("add", str(source))
    finally:
        os.close(holder)
    assert refused.exit_code == 6
    assert "another huron command holds the lock" in refused.stderr
    assert sum(clock.slept) == pytest.approx(LOCK_WAIT)
    assert ready.working().empty
    ready.ok("add", str(source))


def test_a_push_fails_at_once_while_another_push_of_the_copy_runs(
    ready: Cli, tmp_path: Path
) -> None:
    source = tmp_path / "b.txt"
    source.write_text("b")
    ready.ok("add", str(source))
    holder = hold(ready.state.root / "collections" / ready.config_current() / "push.lock")
    try:
        refused = ready.run("push")
    finally:
        os.close(holder)
    assert refused.exit_code == 6
    assert "another `huron push` of this working copy holds the push lock" in refused.stderr
    assert [add.rel_path for add in ready.working().adds] == ["b.txt"]
    ready.ok("push")


def test_commands_stop_when_the_state_root_is_on_nfs(ready: Cli, tmp_path: Path) -> None:
    ready.state = LocalState(ready.state.root, filesystem=lambda path: "nfs")
    source = tmp_path / "b.txt"
    source.write_text("b")
    refused = ready.run("add", str(source))
    assert refused.exit_code == 1 and "XDG_STATE_HOME" in refused.stderr
    assert ready.run("status").exit_code == 0


def test_commands_refuse_state_that_the_cli_cannot_use_without_an_unexpected_failure(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ready.state.root
    source = tmp_path / "b.txt"
    source.write_text("b")
    with monkeypatch.context() as patch:
        deny_reading(patch, written(ready.state, ready.config_current()))
        unreadable = ready.run("status")
    (tmp_path / "file").write_text("keep")
    ready.state = LocalState(tmp_path / "file" / "huron")
    below_a_file = ready.run("logout")
    ready.state = LocalState(root)
    real = os.open

    def open_file(path: Any, flags: int, mode: int = 0o777) -> int:
        if str(path).endswith("state.lock"):
            raise OSError(errno.EROFS, os.strerror(errno.EROFS), str(path))
        return real(path, flags, mode)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", open_file)
        no_lock = ready.run("add", str(source))
    for refused, message in (
        (unreadable, "error: the CLI cannot read"),
        (below_a_file, "error: the CLI cannot save"),
        (no_lock, "error: the CLI cannot save"),
    ):
        assert refused.exit_code == 1
        assert message in refused.stderr and "hint: " in refused.stderr
        assert "unexpected" not in refused.stderr
    assert ready.working().empty


def test_commands_refuse_a_working_copy_file_of_another_collection(
    ready: Cli, tmp_path: Path
) -> None:
    path = written(ready.state, ready.config_current())
    path.write_text(json.dumps({**json.loads(path.read_text()), "collection_id": "c-2"}))
    before = snapshot(path.parent.parent)
    source = tmp_path / "b.txt"
    source.write_text("b")
    for argv in (("status",), ("add", str(source)), ("push",)):
        refused = ready.run(*argv)
        assert refused.exit_code == 1, argv
        assert f"error: {path} is not a valid working copy file" in refused.stderr
        assert "unexpected" not in refused.stderr
    assert snapshot(path.parent.parent) == before


@pytest.mark.parametrize("argv", [("login", "--device"), ("logout",)])
def test_login_and_logout_fail_with_exit_code_6_when_another_holds_the_state_lock(
    cli: Cli, argv: tuple[str, ...]
) -> None:
    cli.login_as("erin")
    before = cli.state.read_tokens()
    cli.state = LocalState(cli.state.root, lock_wait=0.0)
    holder = hold(cli.state.root / "state.lock")
    try:
        refused = cli.run(*argv)
    finally:
        os.close(holder)
    assert refused.exit_code == 6
    assert "another huron command holds the lock" in refused.stderr
    assert cli.state.read_tokens() == before
