"""``huron push`` uploads each staged file through tusd and commits the sealed uploads."""

import base64
import hashlib
import io
import json
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from huron.applications.cli.client import ApiClient
from huron.applications.cli.deadline import Deadline
from huron.applications.cli.errors import CliError, ExitCode
from huron.applications.cli.localstate import StagedAdd, WorkingState
from huron.applications.cli.uploads import CHUNK_SIZE, Uploader, UploadService
from huron.core.storage import UPLOADS, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import rooted
from tests.support.cli import Cli
from tests.support.clock import MonotonicClock
from tests.support.tus import TUS_URL, FakeTus
from tests.unit.cli.conftest import PREFIX

COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
#: The service's hook timeout here: three reads of an unsealed upload, five seconds apart.
HOOK_TIMEOUT = 10
#: The upload IDs that the fixed answers of the uploader's tests name.
U1 = "0190d5a4-0000-7000-8000-0000000000e1"
U2 = "0190d5a4-0000-7000-8000-0000000000e2"
#: The timeout of each request of the uploader's tests, unless a deadline limits it.
TIMEOUT = 30.0
#: The ways in which the answer to a request that reached tusd is lost.
LOST_ANSWERS = [
    pytest.param(httpx.ReadTimeout("late"), id="late"),
    pytest.param(httpx.ReadError("connection reset"), id="reset"),
    pytest.param(httpx.RemoteProtocolError("server disconnected"), id="disconnected"),
]


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """The CLI over a service that holds ``share`` as its lake and takes uploads of 1000 bytes."""
    running = Cli(
        tmp_path,
        rooted(share),
        PREFIX,
        lake=share,
        upload_hook_timeout=timedelta(seconds=HOOK_TIMEOUT),
        max_upload_bytes=1000,
    )
    yield running
    running.close()


def tus(cli: Cli) -> FakeTus:
    assert cli.tus is not None
    return cli.tus


def stage(cli: Cli) -> WorkingState:
    return cli.working()


def staged(cli: Cli, tmp_path: Path, name: str, data: bytes) -> Path:
    """Write ``data`` to a local file ``name`` and stage it."""
    source = tmp_path / name
    source.write_bytes(data)
    cli.ok("add", str(source))
    return source


def recorded(cli: Cli) -> dict[str, str]:
    """The recorded files of the current collection: path to sha256."""
    files = json.loads(cli.ok("-o", "json", "get", "files").stdout)
    return {item["rel_path"]: item["sha256"] for item in files}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_a_push_uploads_through_tusd_and_commits_the_sealed_upload(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    pushed = ready.ok("push", "-m", "first")
    assert "version 3 → 4, +1 −0 files" in pushed.stdout
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}
    assert stage(ready).empty


def test_an_empty_file_finishes_in_the_creation_request(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "empty.txt", b"")
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST"]
    assert share.read_bytes(COLLECTION.joinpath("empty.txt")) == b""
    assert recorded(ready) == {"empty.txt": sha(b"")}


def test_a_dropped_patch_continues_in_the_same_push(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alphabet")
    tus(ready).drop_after = 3
    pushed = ready.ok("push")
    assert "uploaded a.txt (8 bytes)" in pushed.stderr
    (upload_id,) = tus(ready).uploads
    address = f"/files/{upload_id}"
    # The fake tusd refuses a PATCH that does not start at its offset of 3.
    assert tus(ready).requests == [
        ("POST", "/files/"),
        ("PATCH", address),
        ("HEAD", address),
        ("PATCH", address),
    ]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alphabet"
    assert recorded(ready) == {"a.txt": sha(b"alphabet")}
    assert stage(ready).empty


def test_an_upload_that_tusd_lost_after_a_dropped_patch_gets_a_new_upload_id_in_the_same_attempt(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alphabet")
    fake = tus(ready)
    fake.drop_after = 3
    forward = ready.router.tus
    assert forward is not None
    lost: list[StagedAdd] = []

    class LoseBeforeHead(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                ready.router.tus = forward
                (add,) = stage(ready).adds
                assert add.upload_id is not None
                lost.append(add)
                fake.uploads.clear()
                for name in (add.upload_id, f"{add.upload_id}.info"):
                    share.remove_file(UPLOADS.joinpath(name))
            return forward.handle_request(request)

    ready.router.tus = LoseBeforeHead()
    ready.ok("push")
    (first,) = lost
    assert first.attempt_id is not None
    (second,) = fake.uploads
    assert fake.requests == [
        ("POST", "/files/"),
        ("PATCH", f"/files/{first.upload_id}"),
        ("HEAD", f"/files/{first.upload_id}"),
        ("POST", "/files/"),
        ("PATCH", f"/files/{second}"),
    ]
    assert second != first.upload_id
    assert attempt(ready, first.attempt_id)["upload_id"] == second
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alphabet"
    assert stage(ready).empty


def test_a_file_staged_during_the_uploads_stays_staged_for_the_next_push(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    later = tmp_path / "b.txt"
    later.write_bytes(b"beta")
    forward = ready.router.tus
    assert forward is not None

    class StageOnPatch(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "PATCH":
                ready.router.tus = forward
                ready.ok("add", str(later))
            return forward.handle_request(request)

    ready.router.tus = StageOnPatch()
    assert "version 3 → 4, +1 −0 files" in ready.ok("push").stdout
    assert recorded(ready) == {"a.txt": sha(b"alpha")}
    after = stage(ready)
    assert ([add.rel_path for add in after.adds], after.base_version) == (["b.txt"], 4)
    assert after.adds[0].attempt_id is None
    ready.ok("push")
    assert recorded(ready) == {"a.txt": sha(b"alpha"), "b.txt": sha(b"beta")}


def test_a_file_unstaged_during_its_upload_is_left_out_of_the_commit(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    forward = ready.router.tus
    assert forward is not None
    unstaged: list[httpx.Request] = []

    class UnstageOnPatch(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "PATCH" and not unstaged:
                unstaged.append(request)
                ready.ok("rm", "a.txt")
            return forward.handle_request(request)

    ready.router.tus = UnstageOnPatch()
    assert "version 3 → 4, +0 −0 files" in ready.ok("push").stdout
    assert len(unstaged) == 1 and stage(ready).empty
    assert stage(ready).base_version == 4 and recorded(ready) == {}


def attempt(cli: Cli, attempt_id: str) -> dict[str, object]:
    """The upload attempt as its owner reads it on the service."""
    services, _, _ = cli.services()
    found: dict[str, object] = services.api().get(f"/api/v1/upload-attempts/{attempt_id}")
    return found


def test_an_attempt_unknown_to_the_service_is_created_with_the_same_attempt_id(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    attempt_id = str(uuid.uuid4())
    with ready.state.changing(ready.config_current()) as current:
        current.adds[0].attempt_id, current.adds[0].upload_id = attempt_id, U1
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert attempt(ready, attempt_id)["state"] == "consumed"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_an_attempt_id_the_service_refuses_is_reported(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    with ready.state.changing(ready.config_current()) as current:
        current.adds[0].attempt_id = "nope"
    refused = ready.run("push")
    assert refused.exit_code == 7 and "REQUEST_INVALID" in refused.stderr
    assert tus(ready).requests == []


def test_bytes_that_changed_on_the_way_commit_nothing(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).corrupt = True
    mismatch = ready.run("push")
    assert mismatch.exit_code == 6 and "[UPLOAD_INELIGIBLE]" in mismatch.stderr
    assert "holds a different file" in mismatch.stderr
    assert recorded(ready) == {}


def lose_the_answer(fake: FakeTus) -> None:
    fake.lose = "PATCH"


@pytest.mark.parametrize(
    "fault",
    [
        lambda fake: setattr(fake, "finish_status", 500),
        lambda fake: setattr(fake, "finish_status", 502),
        lambda fake: setattr(fake, "finish_status", 504),
        lose_the_answer,
    ],
    ids=["500", "502", "504", "no answer"],
)
def test_an_unclear_final_answer_reads_the_upload_attempt(
    ready: Cli, share: MemoryStorage, tmp_path: Path, fault: Callable[[FakeTus], None]
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    fault(tus(ready))
    pushed = ready.ok("push")
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


@pytest.mark.parametrize(
    ("status", "dropped"),
    [(504, False), (None, False), (None, True)],
    ids=["504", "an answer", "a drop after the last byte"],
)
def test_a_final_patch_whose_hook_never_ran_is_sealed_by_the_attempt_read(
    ready: Cli, share: MemoryStorage, tmp_path: Path, status: int | None, dropped: bool
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    fake = tus(ready)
    # A drop ends the PATCH before tusd's hook, so only the answers need ``skip_finish``.
    fake.finish_status, fake.skip_finish = status, not dropped
    fake.drop_after = 5 if dropped else None
    pushed = ready.ok("push")
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_an_upload_that_tusd_still_holds_is_kept_for_the_next_push(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).hold_lock = True
    held = ready.run("push")
    assert held.exit_code == 8
    assert f"the service did not seal a.txt in {HOOK_TIMEOUT} seconds" in held.stderr
    assert "The next push reads the state of the upload" in held.stderr
    assert ready.slept == [5.0, 5.0]
    (add,) = stage(ready).adds
    assert add.attempt_id is not None and add.upload_id is not None
    assert add.attempt_state == "receiving"
    share.remove_file(UPLOADS.joinpath(f"{add.upload_id}.lock"))
    tus(ready).requests.clear()
    again = ready.ok("push")
    assert tus(ready).requests == []
    assert "a.txt is on the service from an earlier push" in again.stderr
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_lost_creation_answer_makes_no_second_upload(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).lose = "POST"
    lost = ready.run("push")
    assert lost.exit_code == 1 and "The next push continues the upload" in lost.stderr
    (add,) = stage(ready).adds
    assert add.attempt_id is not None and add.upload_id is None
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD", "PATCH"]
    assert len(tus(ready).uploads) == 1
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def test_a_failed_upload_keeps_its_ids_and_the_next_push_starts_a_new_attempt(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).info_size = 4
    failed = ready.run("push")
    assert failed.exit_code == 1 and "[UPLOAD_SIZE_MISMATCH]" in failed.stderr
    (first,) = stage(ready).adds
    assert first.attempt_id is not None and first.upload_id is not None
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


@pytest.mark.parametrize(
    ("method", "status", "exit_code", "message"),
    [
        ("POST", 401, 3, "the upload proxy did not accept your token"),
        ("PATCH", 403, 4, "this upload belongs to another user, or it does not take bytes now"),
    ],
)
def test_the_proxy_refusals_are_explained(
    ready: Cli, tmp_path: Path, method: str, status: int, exit_code: int, message: str
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).refuse[method] = status
    refused = ready.run("push")
    assert refused.exit_code == exit_code and message in refused.stderr
    assert ("run `huron login`" in refused.stderr) is (status == 401)
    assert recorded(ready) == {}


def test_a_refused_creation_reports_the_problem(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "big.bin", b"x" * 1001)
    refused = ready.run("push")
    assert refused.exit_code == 1
    assert (
        "the upload has 1001 bytes. The maximum is 1000 bytes [UPLOAD_TOO_LARGE]" in refused.stderr
    )
    assert stage(ready).adds[0].upload_id is None


def test_a_service_without_uploads_refuses_the_push(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    monkeypatch.setattr(ready.runtime.settings, "uploads_url", None)
    refused = ready.run("push")
    assert refused.exit_code == 1
    assert "the Huron service does not accept uploads" in refused.stderr
    assert "`lake_path` and `uploads_url`" in refused.stderr
    assert tus(ready).requests == []


def test_a_push_of_removals_alone_needs_no_uploads(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    ready.ok("push")
    ready.ok("rm", "a.txt")
    monkeypatch.setattr(ready.runtime.settings, "uploads_url", None)
    assert "+0 −1 files" in ready.ok("push").stdout


def test_a_push_after_a_refused_commit_skips_the_sealed_uploads(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    staged(ready, tmp_path, "b.txt", b"bravo")
    someone_else_commits_during_the_push(ready)
    assert ready.run("push").exit_code == 6
    assert all(add.attempt_state == "ready" for add in stage(ready).adds)
    ready.ok("pull")
    tus(ready).requests.clear()
    retried = ready.ok("push")
    assert tus(ready).requests == []
    assert "a.txt is on the service from an earlier push" in retried.stderr
    assert recorded(ready) == {"a.txt": sha(b"alpha"), "b.txt": sha(b"bravo")}


def touch_later(path: Path) -> None:
    """Move the modification time of ``path`` one second later, keeping its bytes."""
    later = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(later, later))


def rewrite_as_link(path: Path) -> None:
    """Put a link to a copy of ``path`` at ``path``, with the same bytes and times."""
    info = path.stat()
    target = path.with_name(f"{path.name}.target")
    target.write_bytes(path.read_bytes())
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
    path.unlink()
    path.symlink_to(target)


@pytest.mark.parametrize(
    "change",
    [
        lambda path: path.write_bytes(b"alphabet"),
        lambda path: path.write_bytes(b"alp"),
        lambda path: (path.write_bytes(b"bravo"), touch_later(path)),
        rewrite_as_link,
    ],
    ids=["grows", "shrinks", "same size and a new modification time", "replaced by a link"],
)
def test_a_file_that_changed_after_add_stops_the_push_with_its_name(
    ready: Cli, tmp_path: Path, change: Callable[[Path], object]
) -> None:
    source = staged(ready, tmp_path, "a.txt", b"alpha")
    change(source)
    refused = ready.run("push")
    assert refused.exit_code == 2
    assert f"{source} changed after you staged it as a.txt" in refused.stderr
    assert f"run `huron add {source} --as a.txt`. To unstage it, run `huron rm a.txt`" in (
        refused.stderr
    )
    assert tus(ready).requests == [] and recorded(ready) == {}


def test_a_file_removed_after_add_stops_the_push_with_its_name(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha").unlink()
    refused = ready.run("push")
    assert refused.exit_code == 2
    assert (
        f"the CLI cannot read {tmp_path / 'a.txt'}, which you staged as a.txt:"
        " No such file or directory"
    ) in refused.stderr
    assert tus(ready).requests == []


def test_a_change_that_keeps_the_size_and_modification_time_fails_the_commit(
    ready: Cli, tmp_path: Path
) -> None:
    source = staged(ready, tmp_path, "a.txt", b"alpha")
    info = source.stat()
    source.write_bytes(b"bravo")
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    refused = ready.run("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert refused.exit_code == 6 and "[UPLOAD_INELIGIBLE]" in refused.stderr
    assert "holds a different file" in refused.stderr
    assert recorded(ready) == {}


def test_a_file_changed_after_its_upload_is_uploaded_again_once_staged_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    source = staged(ready, tmp_path, "a.txt", b"alpha")
    someone_else_commits_during_the_push(ready)
    assert ready.run("push").exit_code == 6
    ready.ok("pull")
    source.write_bytes(b"bravo")
    touch_later(source)
    assert "changed after you staged it" in ready.run("push").stderr
    ready.ok("add", str(source))
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"bravo"
    assert recorded(ready) == {"a.txt": sha(b"bravo")}


def test_a_location_on_another_host_is_not_followed(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).location_base = "https://evil.example:8443/elsewhere/"
    ready.ok("push")
    assert [path.startswith("/files/") for _, path in tus(ready).requests] == [True, True]
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_commit_that_waits_reads_the_state_of_its_request_until_it_succeeds(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    monkeypatch.setattr("huron.applications.api.routes.v1.endpoints.files.PUBLISH_WAIT", 0.0)
    pushed = ready.ok("push")
    assert "version 3 → 4, +1 −0 files" in pushed.stdout
    assert ready.slept and set(ready.slept) == {5.0}
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def someone_else_commits_during_the_push(cli: Cli) -> None:
    """Make the contributor commit as the push sends its commit, so the service refuses it."""
    collection_id = cli.config_current()
    version = cli.working().base_version

    def commit(request: httpx.Request) -> None:
        if request.url.path.endswith("/commits") and "dry_run" not in request.url.params:
            cli.router.observe = None
            cli.commit_nothing(collection_id, version)

    cli.router.observe = commit


def test_a_commit_refused_after_the_uploads_keeps_the_uploads(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    someone_else_commits_during_the_push(ready)
    refused = ready.run("push")
    assert refused.exit_code == 6 and "BASE_VERSION_CONFLICT" in refused.stderr
    (add,) = stage(ready).adds
    assert (add.sha256, add.attempt_state, add.upload_id is not None) == (
        sha(b"alpha"),
        "ready",
        True,
    )
    assert stage(ready).pending_commit is None


# A creation that races with another creation of the same attempt: the creation rule refuses it
# with the state of the attempt, and the push continues from that state.


def create_upload(
    cli: Cli, attempt_id: str, data: bytes, *, rel_path: str = "a.txt", send: bool = True
) -> str:
    """Create the upload of ``data`` for ``attempt_id`` as the logged-in user, as another
    process does, and with ``send`` send all its bytes; the upload ID.
    """
    tokens = cli.state.read_tokens()
    assert tokens is not None
    metadata = {"attempt_id": attempt_id, "collection": cli.config_current(), "rel_path": rel_path}
    headers = {
        "Authorization": f"Bearer {tokens.huron_token}",
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(len(data)),
        "Upload-Metadata": ",".join(f"{key} {b64(value)}" for key, value in metadata.items()),
    }
    created = tus(cli).handle(httpx.Request("POST", TUS_URL, headers=headers))
    assert created.status_code == 201
    upload_id = created.headers["Location"].rsplit("/", 1)[-1]
    if send:
        patch = {**headers, "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"}
        address = f"{TUS_URL}{upload_id}"
        sent = tus(cli).handle(httpx.Request("PATCH", address, headers=patch, content=data))
        assert sent.is_success
    return upload_id


def race(cli: Cli, monkeypatch: pytest.MonkeyPatch, act: Callable[[str], str]) -> list[str]:
    """Run ``act`` with the attempt ID once the service answered the push's first read of it.

    Returns the upload ID that ``act`` gives, once it ran.
    """
    forward = cli.router.handle_request
    made: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        response = forward(request)
        if request.url.path.startswith("/api/v1/upload-attempts/") and not made:
            made.append(act(request.url.path.rsplit("/", 1)[-1]))
        return response

    monkeypatch.setattr(cli.router, "handle_request", handle)
    return made


def test_a_creation_refused_as_receiving_continues_the_named_upload(
    ready: Cli, share: MemoryStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    made = race(
        ready,
        monkeypatch,
        lambda attempt_id: create_upload(ready, attempt_id, b"alpha", send=False),
    )
    ready.ok("push")
    (upload_id,) = made
    assert tus(ready).requests == [
        ("POST", "/files/"),
        ("POST", "/files/"),
        ("HEAD", f"/files/{upload_id}"),
        ("PATCH", f"/files/{upload_id}"),
    ]
    assert len(tus(ready).uploads) == 1
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def test_a_creation_refused_as_ready_uses_the_sealed_upload(
    ready: Cli, share: MemoryStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    made = race(ready, monkeypatch, lambda attempt_id: create_upload(ready, attempt_id, b"alpha"))
    pushed = ready.ok("push")
    assert "a.txt is on the service from an earlier push" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH", "POST"]
    assert list(tus(ready).uploads) == made
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def test_a_creation_refused_as_sealing_waits_for_the_seal(
    ready: Cli, share: MemoryStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")

    def sealing(attempt_id: str) -> str:
        tus(ready).skip_finish = True
        upload_id = create_upload(ready, attempt_id, b"alpha")
        ready.loop.call(ready.runtime.attempts.start_seal(uuid.UUID(upload_id)))
        return upload_id

    made = race(ready, monkeypatch, sealing)
    pushed = ready.ok("push")
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH", "POST"]
    assert list(tus(ready).uploads) == made
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def test_a_creation_refused_after_the_attempt_ended_starts_a_new_attempt(
    ready: Cli, share: MemoryStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")

    def cancelled(attempt_id: str) -> str:
        upload_id = create_upload(ready, attempt_id, b"alpha", send=False)
        services, _, _ = ready.services()
        services.api().post(f"/api/v1/uploads/{upload_id}/cancel")
        return attempt_id

    made = race(ready, monkeypatch, cancelled)
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "POST", "POST", "PATCH"]
    (ended,) = made
    assert attempt(ready, ended)["state"] == "cancelled"
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def test_a_creation_refused_for_a_different_file_is_reported(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    race(
        ready,
        monkeypatch,
        lambda attempt_id: create_upload(
            ready, attempt_id, b"other", rel_path="other.txt", send=False
        ),
    )
    refused = ready.run("push")
    assert refused.exit_code == 6 and "[ATTEMPT_ID_CONFLICT]" in refused.stderr
    assert "is for a different file" in refused.stderr
    assert recorded(ready) == {}


# The uploader alone, against fixed answers.


class Endpoint:
    """The tus endpoint and the API with fixed answers, for the uploader alone.

    An answer that is a transport error is raised, as a dropped or late answer is. ``during``
    runs as each request arrives.
    """

    def __init__(
        self,
        *answers: httpx.Response | httpx.TransportError,
        during: Callable[[httpx.Request], None] | None = None,
    ) -> None:
        self.answers = list(answers)
        self.during = during
        self.sent: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if self.during is not None:
            self.during(request)
        answer = self.answers.pop(0)
        if isinstance(answer, httpx.TransportError):
            raise answer
        return answer


def uploader(
    endpoint: Endpoint,
    lines: list[str],
    chunk_size: int = 4,
    clock: MonotonicClock | None = None,
) -> Uploader:
    """The uploader with a hook timeout of 10 seconds, on ``clock``."""
    clock = clock or MonotonicClock()
    http = httpx.Client(transport=httpx.MockTransport(endpoint), timeout=TIMEOUT)
    api = ApiClient(http, "http://huron.test", lambda: "token", clock.sleep)
    service = UploadService(TUS_URL, 10.0)
    return Uploader(
        http,
        api,
        lambda: "token",
        service,
        deadline=lambda seconds: Deadline(seconds, clock, clock.sleep),
        report=lines.append,
        chunk_size=chunk_size,
    )


def local(tmp_path: Path, data: bytes) -> StagedAdd:
    """The add of a new local file ``f.bin`` that holds ``data``, as ``huron add`` records it."""
    source = tmp_path / "f.bin"
    source.write_bytes(data)
    return StagedAdd("f.bin", str(source), len(data), source.stat().st_mtime_ns, sha(data))


def resumable(tmp_path: Path, data: bytes, attempt_state: str | None = None) -> StagedAdd:
    """A staged add whose earlier push created the attempt ``a1`` with the upload :data:`U1`.

    ``attempt_state`` is the state that the earlier push recorded.
    """
    add = local(tmp_path, data)
    add.attempt_id, add.upload_id, add.attempt_state = "a1", U1, attempt_state
    return add


def records(
    add: StagedAdd,
) -> tuple[list[tuple[str | None, str | None, str | None]], Callable[[], None]]:
    """What each save of the uploader stored of ``add``, and the save function."""
    saved: list[tuple[str | None, str | None, str | None]] = []
    return saved, lambda: saved.append((add.attempt_id, add.upload_id, add.attempt_state))


def unknown() -> httpx.Response:
    """The API's answer to the read of an attempt that it does not know."""
    return httpx.Response(404, json={"code": "NOT_FOUND", "detail": "gone"})


def created(location: str = f"/files/{U1}") -> httpx.Response:
    return httpx.Response(201, headers={"Location": location})


def ready_answer(offset: int) -> httpx.Response:
    """The answer of a final ``PATCH`` whose pre-finish hook sealed the upload."""
    headers = {"Upload-Offset": str(offset), "Huron-Upload-State": "ready"}
    return httpx.Response(204, headers=headers)


def attempt_state(state: str, failure: dict[str, str] | None = None) -> httpx.Response:
    """The API's answer to ``GET /api/v1/upload-attempts/{attempt_id}``."""
    body = {"attempt_id": "a1", "state": state, "upload_id": U1, "failure": failure}
    return httpx.Response(200, json=body)


def refused_as(state: str, upload_id: str | None = None) -> httpx.Response:
    """tusd's answer to a creation that the creation rule refused with ``state``."""
    context = {"attempt_id": "a1", "state": state}
    if upload_id is not None:
        context["upload_id"] = upload_id
    body = {"code": "UPLOAD_STATE_CONFLICT", "detail": "refused", "context": context}
    return httpx.Response(409, json=body)


def held(offset: int, length: int) -> httpx.Response:
    """tusd's answer to a ``HEAD`` of an upload of ``length`` bytes that holds ``offset``."""
    return httpx.Response(200, headers={"Upload-Offset": str(offset), "Upload-Length": str(length)})


def paths(endpoint: Endpoint) -> list[str]:
    return [f"{request.method} {request.url.path}" for request in endpoint.sent]


def steps(endpoint: Endpoint) -> list[str]:
    """Each request as ``METHOD path``: a read of the attempt as ``GET attempt``, and a
    ``PATCH`` with its ``Upload-Offset``.
    """
    named = []
    for request in endpoint.sent:
        if request.url.path.startswith("/api/v1/upload-attempts/"):
            named.append("GET attempt")
        elif request.method == "PATCH":
            named.append(f"PATCH {request.url.path} {request.headers['Upload-Offset']}")
        else:
            named.append(f"{request.method} {request.url.path}")
    return named


def test_the_uploader_reads_the_attempt_then_sends_chunks_with_a_progress_line(
    tmp_path: Path,
) -> None:
    lines: list[str] = []
    endpoint = Endpoint(
        unknown(),
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        ready_answer(10),
    )
    add = local(tmp_path, b"0123456789")
    saved, save = records(add)
    uploader(endpoint, lines).upload("c1", add, save)
    assert lines == [
        "sent 4 of 10 bytes of f.bin",
        "sent 8 of 10 bytes of f.bin",
        "uploaded f.bin (10 bytes)",
    ]
    attempt_id = add.attempt_id
    assert attempt_id is not None
    assert saved == [
        (attempt_id, None, None),
        (attempt_id, U1, "receiving"),
        (attempt_id, U1, "ready"),
    ]
    assert paths(endpoint) == [
        f"GET /api/v1/upload-attempts/{attempt_id}",
        "POST /files/",
        *[f"PATCH /files/{U1}"] * 3,
    ]
    assert [str(request.url) for request in endpoint.sent[2:]] == [f"{TUS_URL}{U1}"] * 3
    offsets = [request.headers["Upload-Offset"] for request in endpoint.sent[2:]]
    assert offsets == ["0", "4", "8"]
    creation = endpoint.sent[1]
    assert creation.headers["Tus-Resumable"] == "1.0.0"
    assert creation.headers["Authorization"] == "Bearer token"
    assert creation.headers["Upload-Metadata"] == (
        f"attempt_id {b64(attempt_id)},collection YzE=,rel_path Zi5iaW4="
    )


def test_a_chunk_has_at_most_64_mib(tmp_path: Path) -> None:
    source = tmp_path / "f.bin"
    with source.open("wb") as written:
        written.truncate(CHUNK_SIZE + 1)
    add = StagedAdd("f.bin", str(source), CHUNK_SIZE + 1, source.stat().st_mtime_ns, "ab" * 32)
    endpoint = Endpoint(
        unknown(),
        created(),
        httpx.Response(204, headers={"Upload-Offset": str(CHUNK_SIZE)}),
        ready_answer(CHUNK_SIZE + 1),
    )
    clock = MonotonicClock()
    http = httpx.Client(transport=httpx.MockTransport(endpoint))
    service = UploadService(TUS_URL, 10.0)
    Uploader(
        http,
        ApiClient(http, "http://huron.test", lambda: "token", clock.sleep),
        lambda: "token",
        service,
        deadline=lambda seconds: Deadline(seconds, clock, clock.sleep),
        report=lambda _: None,
    ).upload("c1", add, lambda: None)
    assert CHUNK_SIZE == 64 * 1024 * 1024
    assert [len(request.content) for request in endpoint.sent[2:]] == [CHUNK_SIZE, 1]


def test_the_uploader_builds_the_address_from_the_uploads_url(tmp_path: Path) -> None:
    endpoint = Endpoint(
        unknown(), created(f"https://evil.example:8443/elsewhere/{U1}"), ready_answer(3)
    )
    uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert str(endpoint.sent[2].url) == f"{TUS_URL}{U1}"


@pytest.mark.parametrize("location", [None, "/files/not-an-id"])
def test_the_uploader_refuses_a_creation_without_an_upload_address(
    tmp_path: Path, location: str | None
) -> None:
    answer = httpx.Response(201) if location is None else created(location)
    with pytest.raises(CliError, match="did not give the address of a new upload"):
        uploader(Endpoint(unknown(), answer), []).upload(
            "c1", local(tmp_path, b"abc"), lambda: None
        )


def test_the_uploader_reports_an_unexpected_status(tmp_path: Path) -> None:
    endpoint = Endpoint(unknown(), httpx.Response(507))
    with pytest.raises(CliError, match="the upload service answered HTTP 507"):
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)


def test_the_uploader_refuses_a_file_that_shrinks_while_it_is_sent(tmp_path: Path) -> None:
    # Chunks of whole read buffers, so the read after the first chunk sees the truncation.
    chunk = 2 * io.DEFAULT_BUFFER_SIZE
    add = local(tmp_path, b"x" * 2 * chunk)

    def truncate(request: httpx.Request) -> None:
        if request.method == "PATCH":
            Path(add.source).write_bytes(b"x" * chunk)

    endpoint = Endpoint(
        unknown(),
        created(),
        httpx.Response(204, headers={"Upload-Offset": str(chunk)}),
        during=truncate,
    )
    with pytest.raises(CliError, match="changed after you staged it"):
        uploader(endpoint, [], chunk_size=chunk).upload("c1", add, lambda: None)


def read_timeout(request: httpx.Request) -> float | None:
    timeout: dict[str, float | None] = request.extensions["timeout"]
    return timeout["read"]


def test_the_request_that_finishes_an_upload_waits_for_the_hook(tmp_path: Path) -> None:
    endpoint = Endpoint(
        unknown(),
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        ready_answer(10),
    )
    uploader(endpoint, []).upload("c1", local(tmp_path, b"0123456789"), lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [TIMEOUT] * 4 + [70.0]


def test_the_creation_of_an_empty_file_waits_for_the_hook(tmp_path: Path) -> None:
    finished = httpx.Response(
        201, headers={"Location": f"/files/{U1}", "Huron-Upload-State": "ready"}
    )
    endpoint = Endpoint(unknown(), finished)
    add = local(tmp_path, b"")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [TIMEOUT, 70.0]
    assert (add.upload_id, add.attempt_state) == (U1, "ready")


#: The requests before the final ``PATCH`` of ``abc`` in one chunk.
ONE_CHUNK = ["GET attempt", "POST /files/", f"PATCH /files/{U1} 0"]


@pytest.mark.parametrize("lost", LOST_ANSWERS)
@pytest.mark.parametrize(
    ("data", "exchange", "expected", "upload_id"),
    [
        pytest.param(
            b"abc",
            lambda lost: [unknown(), created(), lost, attempt_state("ready")],
            [*ONE_CHUNK, "GET attempt"],
            U1,
            id="sealed",
        ),
        pytest.param(
            b"abc",
            lambda lost: [
                unknown(),
                created(),
                lost,
                attempt_state("receiving"),
                held(2, 3),
                ready_answer(3),
            ],
            [*ONE_CHUNK, "GET attempt", f"HEAD /files/{U1}", f"PATCH /files/{U1} 2"],
            U1,
            id="bytes missing",
        ),
        pytest.param(
            b"abc",
            lambda lost: [
                unknown(),
                created(),
                lost,
                attempt_state("receiving"),
                held(3, 3),
                attempt_state("ready"),
            ],
            [*ONE_CHUNK, "GET attempt", f"HEAD /files/{U1}", "GET attempt"],
            U1,
            id="all bytes held",
        ),
        pytest.param(
            b"abc",
            lambda lost: [
                unknown(),
                created(),
                lost,
                attempt_state("receiving"),
                httpx.Response(404),
                created(f"/files/{U2}"),
                ready_answer(3),
            ],
            [
                *ONE_CHUNK,
                "GET attempt",
                f"HEAD /files/{U1}",
                "POST /files/",
                f"PATCH /files/{U2} 0",
            ],
            U2,
            id="upload gone from tusd",
        ),
        pytest.param(
            b"0123456789",
            lambda lost: [
                unknown(),
                created(),
                httpx.Response(204, headers={"Upload-Offset": "4"}),
                httpx.Response(204, headers={"Upload-Offset": "8"}),
                lost,
                attempt_state("receiving"),
                held(9, 10),
                ready_answer(10),
            ],
            [
                "GET attempt",
                "POST /files/",
                f"PATCH /files/{U1} 0",
                f"PATCH /files/{U1} 4",
                f"PATCH /files/{U1} 8",
                "GET attempt",
                f"HEAD /files/{U1}",
                f"PATCH /files/{U1} 9",
            ],
            U1,
            id="final chunk kept in part",
        ),
    ],
)
def test_a_late_final_answer_reads_the_upload_attempt(
    tmp_path: Path,
    lost: httpx.TransportError,
    data: bytes,
    exchange: Callable[[httpx.TransportError], list[httpx.Response | httpx.TransportError]],
    expected: list[str],
    upload_id: str,
) -> None:
    lines: list[str] = []
    endpoint = Endpoint(*exchange(lost))
    add = local(tmp_path, data)
    uploader(endpoint, lines).upload("c1", add, lambda: None)
    assert (add.upload_id, add.attempt_state) == (upload_id, "ready")
    assert lines[-1] == f"uploaded f.bin ({len(data)} bytes)"
    assert steps(endpoint) == expected
    patches = [request for request in endpoint.sent if request.method == "PATCH"]
    for patch in patches:
        start = int(patch.headers["Upload-Offset"])
        assert patch.content == data[start : start + len(patch.content)]
    creations = [request for request in endpoint.sent if request.method == "POST"]
    assert len({request.headers["Upload-Metadata"] for request in creations}) == 1
    assert endpoint.answers == []


@pytest.mark.parametrize(
    "answer",
    [
        *LOST_ANSWERS,
        *[pytest.param(httpx.Response(status), id=str(status)) for status in (500, 502, 504)],
    ],
)
def test_an_unclear_final_answer_that_moved_no_byte_stops_the_push_and_keeps_the_upload(
    tmp_path: Path, answer: httpx.TransportError | httpx.Response
) -> None:
    endpoint = Endpoint(unknown(), created(), answer, attempt_state("receiving"), held(0, 3))
    add = local(tmp_path, b"abc")
    saved, save = records(add)
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, save)
    if isinstance(answer, httpx.Response):
        message = f"the upload service answered HTTP {answer.status_code}"
    else:
        message = f"the upload service at {TUS_URL} is unreachable: {answer}"
    assert raised.value.message == message
    assert (raised.value.exit_code, raised.value.hint) == (
        ExitCode.FAILED,
        "run `huron push` again. The next push continues the upload",
    )
    assert saved[-1] == (add.attempt_id, U1, "receiving")
    assert steps(endpoint) == [*ONE_CHUNK, "GET attempt", f"HEAD /files/{U1}"]
    endpoint.answers = [attempt_state("receiving"), held(0, 3), ready_answer(3)]
    uploader(endpoint, []).upload("c1", add, save)
    assert saved[-1] == (add.attempt_id, U1, "ready")
    assert steps(endpoint)[5:] == ["GET attempt", f"HEAD /files/{U1}", f"PATCH /files/{U1} 0"]


def test_a_complete_upload_after_a_late_final_answer_is_read_until_the_hook_timeout(
    tmp_path: Path,
) -> None:
    clock = MonotonicClock()
    endpoint = Endpoint(
        unknown(),
        created(),
        httpx.ReadTimeout("late"),
        attempt_state("receiving"),
        held(3, 3),
        *[attempt_state("receiving")] * 2,
    )
    add = local(tmp_path, b"abc")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, [], clock=clock).upload("c1", add, lambda: None)
    assert raised.value.message == "the service did not seal f.bin in 10 seconds"
    assert raised.value.exit_code == ExitCode.STORAGE
    assert (add.upload_id, add.attempt_state) == (U1, "receiving")
    assert clock.slept == [5.0, 5.0]
    assert steps(endpoint) == [*ONE_CHUNK, "GET attempt", f"HEAD /files/{U1}", *["GET attempt"] * 2]


def test_an_answer_that_says_the_seal_goes_on_reads_the_attempt_until_it_is_ready(
    tmp_path: Path,
) -> None:
    sealing = httpx.Response(204, headers={"Huron-Upload-State": "sealing"})
    endpoint = Endpoint(
        unknown(), created(), sealing, attempt_state("sealing"), attempt_state("ready")
    )
    add = local(tmp_path, b"abc")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert add.attempt_state == "ready"
    assert len(endpoint.sent) == 5


@pytest.mark.parametrize(
    "states", [["ready"], ["receiving", "ready"]], ids=["sealed", "sealed after a wait"]
)
@pytest.mark.parametrize("answer", [*LOST_ANSWERS, httpx.Response(500)])
def test_an_unclear_answer_to_the_creation_of_an_empty_file_reads_the_attempt(
    tmp_path: Path, answer: httpx.Response | httpx.TransportError, states: list[str]
) -> None:
    endpoint = Endpoint(unknown(), answer, *[attempt_state(state) for state in states])
    add = local(tmp_path, b"")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert (add.upload_id, add.attempt_state) == (U1, "ready")
    attempt_read = f"GET /api/v1/upload-attempts/{add.attempt_id}"
    assert paths(endpoint) == [attempt_read, "POST /files/", *[attempt_read] * len(states)]


@pytest.mark.parametrize(
    ("state", "message", "recorded_state"),
    [
        (unknown(), "the service has no record of the upload of f.bin", "receiving"),
        (attempt_state("cancelled"), "the upload of f.bin is cancelled", "cancelled"),
    ],
)
def test_an_upload_that_is_gone_or_ended_says_so_and_keeps_its_ids(
    tmp_path: Path, state: httpx.Response, message: str, recorded_state: str
) -> None:
    # The service does not know the attempt of an earlier push, so the push creates it again.
    endpoint = Endpoint(unknown(), created(), httpx.Response(504), state)
    add = resumable(tmp_path, b"abc", attempt_state="ready")
    saved, save = records(add)
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, save)
    assert raised.value.message == message
    assert raised.value.hint == (
        "run `huron push` again. The next push starts a new upload of the file"
    )
    assert (add.attempt_id, add.upload_id, add.attempt_state) == ("a1", U1, recorded_state)
    assert saved[0] == ("a1", U1, "receiving")
    assert len(endpoint.sent) == 4


def test_a_failed_attempt_says_why_and_keeps_its_ids(tmp_path: Path) -> None:
    failure = {"code": "UPLOAD_SIZE_MISMATCH", "message": "the sizes differ"}
    endpoint = Endpoint(unknown(), created(), httpx.Response(500), attempt_state("failed", failure))
    add = local(tmp_path, b"abc")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: None)
    assert raised.value.message == "the service did not seal f.bin: the sizes differ"
    assert raised.value.code == "UPLOAD_SIZE_MISMATCH"
    assert (add.upload_id, add.attempt_state) == (U1, "failed")


def test_another_error_of_the_attempt_read_is_raised(tmp_path: Path) -> None:
    refused = httpx.Response(403, json={"code": "FORBIDDEN", "detail": "no"})
    endpoint = Endpoint(unknown(), created(), httpx.Response(502), refused)
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert raised.value.code == "FORBIDDEN"


def test_the_fake_tusd_refuses_requests_without_the_tus_headers(ready: Cli) -> None:
    upload_id = create_upload(ready, str(uuid.uuid4()), b"alpha", send=False)
    address = f"{TUS_URL}{upload_id}"
    tokens = ready.state.read_tokens()
    assert tokens is not None
    bearer = {"Authorization": f"Bearer {tokens.huron_token}"}
    tus_headers = {**bearer, "Tus-Resumable": "1.0.0"}

    def answer(method: str, url: str, headers: dict[str, str], content: bytes = b"") -> int:
        request = httpx.Request(method, url, headers=headers, content=content)
        return tus(ready).handle(request).status_code

    assert answer("POST", TUS_URL, {**bearer, "Upload-Length": "1"}) == 412
    assert answer("HEAD", address, bearer) == 412
    assert answer("HEAD", address, {**bearer, "Tus-Resumable": "0.2.2"}) == 412
    patch = {**tus_headers, "Upload-Offset": "2"}
    assert answer("PATCH", address, patch, b"pha") == 415
    stream = {**patch, "Content-Type": "application/offset+octet-stream"}
    assert answer("PATCH", address, {**stream, "Tus-Resumable": ""}, b"pha") == 412
    assert answer("HEAD", address, tus_headers) == 200


@pytest.mark.parametrize(
    "data", [b"0123456789", b"abc"], ids=["a chunk before the last", "the final chunk"]
)
def test_a_dropped_chunk_reports_the_service_unreachable(tmp_path: Path, data: bytes) -> None:
    endpoint = Endpoint(unknown(), created(), httpx.ConnectError("refused"))
    add = local(tmp_path, data)
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: None)
    assert raised.value.message == f"the upload service at {TUS_URL} is unreachable: refused"
    assert raised.value.hint == "run `huron push` again. The next push continues the upload"
    assert add.upload_id == U1
    attempt_read = f"GET /api/v1/upload-attempts/{add.attempt_id}"
    assert paths(endpoint) == [attempt_read, "POST /files/", f"PATCH /files/{U1}"]


def test_a_resumed_upload_that_is_sealing_is_read_until_it_is_ready(tmp_path: Path) -> None:
    lines: list[str] = []
    endpoint = Endpoint(attempt_state("sealing"), attempt_state("sealing"), attempt_state("ready"))
    add = resumable(tmp_path, b"abc")
    uploader(endpoint, lines).upload("c1", add, lambda: None)
    assert (add.attempt_id, add.upload_id, add.attempt_state) == ("a1", U1, "ready")
    assert lines == ["uploaded f.bin (3 bytes)"]
    assert [request.url.path for request in endpoint.sent] == ["/api/v1/upload-attempts/a1"] * 3


def test_a_resumed_upload_that_ended_keeps_its_ids_and_its_state(tmp_path: Path) -> None:
    endpoint = Endpoint(attempt_state("sealing"), attempt_state("cancelled"))
    add = resumable(tmp_path, b"abc", attempt_state="ready")
    saved, save = records(add)
    with pytest.raises(CliError, match=r"the upload of f\.bin is cancelled"):
        uploader(endpoint, []).upload("c1", add, save)
    assert saved == [("a1", U1, "sealing"), ("a1", U1, "cancelled")]


def test_a_resumed_upload_whose_bytes_tusd_holds_reads_the_attempt(tmp_path: Path) -> None:
    head = httpx.Response(200, headers={"Upload-Offset": "3", "Upload-Length": "3"})
    endpoint = Endpoint(attempt_state("receiving"), head, attempt_state("ready"))
    add = resumable(tmp_path, b"abc")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert add.attempt_state == "ready"
    assert [request.method for request in endpoint.sent] == ["GET", "HEAD", "GET"]


@pytest.mark.parametrize("state", ["consumed", "expired"])
def test_an_attempt_in_another_state_is_replaced_by_a_new_attempt(
    tmp_path: Path, state: str
) -> None:
    endpoint = Endpoint(attempt_state(state), unknown(), created(), ready_answer(3))
    add = resumable(tmp_path, b"abc", attempt_state="ready")
    saved, save = records(add)
    uploader(endpoint, []).upload("c1", add, save)
    attempt_id = add.attempt_id
    assert attempt_id not in (None, "a1")
    assert saved[0] == (attempt_id, None, None)
    assert paths(endpoint)[:3] == [
        "GET /api/v1/upload-attempts/a1",
        f"GET /api/v1/upload-attempts/{attempt_id}",
        "POST /files/",
    ]


def test_a_creation_refused_as_receiving_resumes_the_named_upload(tmp_path: Path) -> None:
    head = httpx.Response(200, headers={"Upload-Offset": "1", "Upload-Length": "3"})
    endpoint = Endpoint(unknown(), refused_as("receiving", U2), head, ready_answer(3))
    add = local(tmp_path, b"abc")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert (add.upload_id, add.attempt_state) == (U2, "ready")
    assert paths(endpoint)[1:] == ["POST /files/", f"HEAD /files/{U2}", f"PATCH /files/{U2}"]
    assert endpoint.sent[-1].content == b"bc"


def test_a_creation_refused_as_receiving_does_not_create_again_when_tusd_lacks_the_upload(
    tmp_path: Path,
) -> None:
    endpoint = Endpoint(unknown(), refused_as("receiving", U2), httpx.Response(404))
    with pytest.raises(CliError, match="the upload service answered HTTP 404"):
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert len(endpoint.sent) == 3


@pytest.mark.parametrize(
    ("request_seconds", "slept", "timeouts"),
    [(0.0, [5.0, 5.0], [10.0, 5.0]), (3.0, [5.0], [10.0, 2.0]), (6.0, [4.0], [10.0])],
    ids=["instant requests", "requests of 3 seconds", "requests of 6 seconds"],
)
def test_the_wait_for_a_seal_counts_the_time_of_its_requests(
    tmp_path: Path, request_seconds: float, slept: list[float], timeouts: list[float]
) -> None:
    clock = MonotonicClock()
    reads: list[httpx.Request] = []

    def take_time(request: httpx.Request) -> None:
        if request.method == "GET" and endpoint.sent[:-1]:
            reads.append(request)
            clock.advance(request_seconds)

    endpoint = Endpoint(*[attempt_state("sealing")] * 4, during=take_time)
    with pytest.raises(CliError, match=r"did not seal f\.bin in 10 seconds"):
        uploader(endpoint, [], clock=clock).upload("c1", resumable(tmp_path, b"abc"), lambda: None)
    assert clock.slept == slept
    assert [read_timeout(request) for request in reads] == timeouts


@pytest.mark.parametrize("answered", [0, 1], ids=["the first read", "a later read"])
def test_a_read_of_the_attempt_that_times_out_at_the_deadline_ends_the_wait_for_the_seal(
    tmp_path: Path, answered: int
) -> None:
    clock = MonotonicClock()
    start = clock.now

    def time_out(request: httpx.Request) -> None:
        if isinstance(endpoint.answers[0], httpx.ReadTimeout):
            timeout = read_timeout(request)
            assert timeout is not None
            clock.advance(timeout)

    endpoint = Endpoint(
        attempt_state("sealing"),
        *[attempt_state("sealing")] * answered,
        httpx.ReadTimeout("late"),
        during=time_out,
    )
    add = resumable(tmp_path, b"abc")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, [], clock=clock).upload("c1", add, lambda: None)
    assert raised.value.message == "the service did not seal f.bin in 10 seconds"
    assert (raised.value.exit_code, raised.value.hint) == (
        ExitCode.STORAGE,
        "run `huron push` again. The next push reads the state of the upload",
    )
    assert (add.attempt_id, add.upload_id, add.attempt_state) == ("a1", U1, "sealing")
    assert endpoint.answers == [] and clock.now - start == 10.0


def test_a_creation_conflict_without_a_problem_document_is_reported(tmp_path: Path) -> None:
    endpoint = Endpoint(unknown(), httpx.Response(409, text="<html>conflict</html>"))
    with pytest.raises(CliError, match="the upload service answered HTTP 409"):
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
