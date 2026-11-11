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
from huron.applications.cli.errors import CliError
from huron.applications.cli.localstate import StagedAdd, WorkingState
from huron.applications.cli.uploads import Uploader, UploadService
from huron.core.storage import UPLOADS, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import rooted
from tests.support.cli import Cli
from tests.support.tus import TUS_URL, FakeTus
from tests.unit.cli.conftest import PREFIX

COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
#: The service's hook timeout here: three reads of an unsealed upload, five seconds apart.
HOOK_TIMEOUT = 10
#: The upload ID that the fixed answers of the uploader's tests name.
U1 = "0190d5a4-0000-7000-8000-0000000000e1"


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


def test_a_dropped_patch_continues_on_the_next_push(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alphabet")
    tus(ready).drop_after = 3
    dropped = ready.run("push")
    assert dropped.exit_code == 1 and "is unreachable" in dropped.stderr
    assert "The next push continues the upload" in dropped.stderr
    (add,) = stage(ready).adds
    assert add.attempt_id is not None and add.upload_id is not None
    assert tus(ready).uploads[add.upload_id].offset == 3
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alphabet"
    assert recorded(ready) == {"a.txt": sha(b"alphabet")}


def test_an_upload_that_tusd_lost_starts_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alphabet")
    tus(ready).drop_after = 3
    assert ready.run("push").exit_code == 1
    first = stage(ready).adds[0].attempt_id
    tus(ready).uploads.clear()
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD", "POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alphabet"
    assert stage(ready).empty and first is not None


def test_a_file_staged_while_a_push_runs_stays_staged_for_the_next_push(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    later = tmp_path / "b.txt"
    later.write_bytes(b"beta")

    def stage_during_the_commit(request: httpx.Request) -> None:
        if request.url.path.endswith("/commits") and "dry_run" not in request.url.params:
            ready.router.observe = None
            ready.ok("add", str(later))

    ready.router.observe = stage_during_the_commit
    assert "version 3 → 4, +1 −0 files" in ready.ok("push").stdout
    assert recorded(ready) == {"a.txt": sha(b"alpha")}
    after = stage(ready)
    assert ([add.rel_path for add in after.adds], after.base_version) == (["b.txt"], 4)
    ready.ok("push")
    assert recorded(ready) == {"a.txt": sha(b"alpha"), "b.txt": sha(b"beta")}


def test_a_file_unstaged_while_its_upload_runs_is_not_staged_again(
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
    ready.ok("push")
    assert len(unstaged) == 1 and stage(ready).empty
    assert stage(ready).base_version == 4


def test_an_attempt_unknown_to_the_service_starts_again(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    with ready.state.changing(ready.config_current()) as current:
        current.adds[0].attempt_id, current.adds[0].upload_id = str(uuid.uuid4()), U1
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]


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


@pytest.mark.parametrize("status", [500, 502, 504])
def test_an_unclear_final_answer_reads_the_upload_attempt(
    ready: Cli, share: MemoryStorage, tmp_path: Path, status: int
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).finish_status = status
    pushed = ready.ok("push")
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


@pytest.mark.parametrize("status", [504, None])
def test_a_final_patch_whose_hook_never_ran_is_sealed_by_the_attempt_read(
    ready: Cli, share: MemoryStorage, tmp_path: Path, status: int | None
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).finish_status, tus(ready).skip_finish = status, True
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
    share.remove_file(UPLOADS.joinpath(f"{add.upload_id}.lock"))
    tus(ready).requests.clear()
    again = ready.ok("push")
    assert tus(ready).requests == []
    assert "a.txt is on the service from an earlier push" in again.stderr
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_failed_upload_prints_the_failure_and_the_next_push_starts_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).info_size = 4
    failed = ready.run("push")
    assert failed.exit_code == 1 and "[UPLOAD_SIZE_MISMATCH]" in failed.stderr
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


def test_a_retried_push_skips_the_sealed_uploads(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    staged(ready, tmp_path, "b.txt", b"bravo")
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    assert all(add.attempt_state == "ready" for add in stage(ready).adds)
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
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    source.write_bytes(b"bravo")
    touch_later(source)
    assert "changed after you staged it" in ready.run("push").stderr
    ready.ok("add", str(source))
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"bravo"
    assert recorded(ready) == {"a.txt": sha(b"bravo")}


def test_an_upload_whose_bytes_all_arrived_is_sealed_by_the_next_push(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).drop_after = 5
    assert ready.run("push").exit_code == 1
    tus(ready).requests.clear()
    pushed = ready.ok("push")
    assert tus(ready).requests == []
    assert "a.txt is on the service from an earlier push" in pushed.stderr
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


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
    assert ready.slept == [5.0]
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


class Endpoint:
    """The tus endpoint and the API with fixed answers, for the uploader alone.

    An answer that is a transport error is raised, as a dropped or late answer is.
    """

    def __init__(
        self,
        *answers: httpx.Response | httpx.TransportError,
        during: Callable[[], None] | None = None,
    ) -> None:
        self.answers = list(answers)
        self.during = during
        self.sent: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if self.during is not None and request.method == "PATCH":
            self.during()
        answer = self.answers.pop(0)
        if isinstance(answer, httpx.TransportError):
            raise answer
        return answer


def uploader(endpoint: Endpoint, lines: list[str], chunk_size: int = 4) -> Uploader:
    http = httpx.Client(transport=httpx.MockTransport(endpoint))
    api = ApiClient(http, "http://huron.test", lambda: "token")
    service = UploadService(TUS_URL, 10.0)
    return Uploader(
        http,
        api,
        lambda: "token",
        service,
        sleep=lambda _: None,
        report=lines.append,
        chunk_size=chunk_size,
    )


def local(tmp_path: Path, data: bytes) -> StagedAdd:
    """The add of a new local file ``f.bin`` that holds ``data``, as ``huron add`` records it."""
    source = tmp_path / "f.bin"
    source.write_bytes(data)
    return StagedAdd("f.bin", str(source), len(data), source.stat().st_mtime_ns, sha(data))


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


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_the_uploader_sends_chunks_with_a_progress_line(tmp_path: Path) -> None:
    lines: list[str] = []
    data = b"0123456789"
    endpoint = Endpoint(
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        ready_answer(10),
    )
    add = local(tmp_path, data)
    saved: list[tuple[str | None, str | None]] = []
    uploader(endpoint, lines).upload(
        "c1", add, lambda: saved.append((add.attempt_id, add.upload_id))
    )
    assert lines == [
        "sent 4 of 10 bytes of f.bin",
        "sent 8 of 10 bytes of f.bin",
        "uploaded f.bin (10 bytes)",
    ]
    assert add.attempt_id is not None
    assert (add.upload_id, add.attempt_state) == (U1, "ready")
    assert saved == [(add.attempt_id, None), (add.attempt_id, U1)]
    assert [str(request.url) for request in endpoint.sent[1:]] == [f"{TUS_URL}{U1}"] * 3
    offsets = [request.headers["Upload-Offset"] for request in endpoint.sent[1:]]
    assert offsets == ["0", "4", "8"]
    creation = endpoint.sent[0]
    assert creation.headers["Tus-Resumable"] == "1.0.0"
    assert creation.headers["Authorization"] == "Bearer token"
    assert creation.headers["Upload-Metadata"] == (
        f"attempt_id {b64(add.attempt_id)},collection YzE=,rel_path Zi5iaW4="
    )


def test_the_uploader_builds_the_address_from_the_uploads_url(tmp_path: Path) -> None:
    endpoint = Endpoint(created(f"https://evil.example:8443/elsewhere/{U1}"), ready_answer(3))
    uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert str(endpoint.sent[1].url) == f"{TUS_URL}{U1}"


@pytest.mark.parametrize("location", [None, "/files/not-an-id"])
def test_the_uploader_refuses_a_creation_without_an_upload_address(
    tmp_path: Path, location: str | None
) -> None:
    answer = httpx.Response(201) if location is None else created(location)
    with pytest.raises(CliError, match="did not give the address of a new upload"):
        uploader(Endpoint(answer), []).upload("c1", local(tmp_path, b"abc"), lambda: None)


def test_the_uploader_reports_an_unexpected_status(tmp_path: Path) -> None:
    endpoint = Endpoint(httpx.Response(507))
    with pytest.raises(CliError, match="the upload service answered HTTP 507"):
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)


def test_the_uploader_refuses_a_file_that_shrinks_while_it_is_sent(tmp_path: Path) -> None:
    # Chunks of whole read buffers, so the read after the first chunk sees the truncation.
    chunk = 2 * io.DEFAULT_BUFFER_SIZE
    add = local(tmp_path, b"x" * 2 * chunk)
    endpoint = Endpoint(
        created(),
        httpx.Response(204, headers={"Upload-Offset": str(chunk)}),
        during=lambda: Path(add.source).write_bytes(b"x" * chunk),
    )
    with pytest.raises(CliError, match="changed after you staged it"):
        uploader(endpoint, [], chunk_size=chunk).upload("c1", add, lambda: None)


def test_a_commit_refused_after_the_uploads_keeps_the_uploads(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    collection_id = ready.config_current()

    def someone_else_commits(request: httpx.Request) -> None:
        if request.url.path.endswith("/commits") and "dry_run" not in request.url.params:
            ready.commit_nothing(collection_id, 3)

    ready.router.observe = someone_else_commits
    refused = ready.run("push")
    assert refused.exit_code == 6 and "BASE_VERSION_CONFLICT" in refused.stderr
    (add,) = stage(ready).adds
    assert (add.sha256, add.attempt_state, add.upload_id is not None) == (
        sha(b"alpha"),
        "ready",
        True,
    )


def read_timeout(request: httpx.Request) -> float | None:
    timeout: dict[str, float | None] = request.extensions["timeout"]
    return timeout["read"]


def test_the_request_that_finishes_an_upload_waits_for_the_hook(tmp_path: Path) -> None:
    endpoint = Endpoint(
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        ready_answer(10),
    )
    uploader(endpoint, []).upload("c1", local(tmp_path, b"0123456789"), lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [5.0, 5.0, 5.0, 70.0]


def test_the_creation_of_an_empty_file_waits_for_the_hook(tmp_path: Path) -> None:
    finished = httpx.Response(
        201, headers={"Location": f"/files/{U1}", "Huron-Upload-State": "ready"}
    )
    endpoint = Endpoint(finished)
    add = local(tmp_path, b"")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [70.0]
    assert (add.upload_id, add.attempt_state) == (U1, "ready")


def test_a_late_final_answer_reads_the_upload_attempt(tmp_path: Path) -> None:
    lines: list[str] = []
    data = b"abc"
    endpoint = Endpoint(created(), httpx.ReadTimeout("late"), attempt_state("ready"))
    add = local(tmp_path, data)
    uploader(endpoint, lines).upload("c1", add, lambda: None)
    assert add.attempt_state == "ready" and lines == ["uploaded f.bin (3 bytes)"]
    assert endpoint.sent[-1].url.path == f"/api/v1/upload-attempts/{add.attempt_id}"


def test_an_answer_that_says_the_seal_goes_on_reads_the_attempt_until_it_is_ready(
    tmp_path: Path,
) -> None:
    sealing = httpx.Response(204, headers={"Huron-Upload-State": "sealing"})
    endpoint = Endpoint(created(), sealing, attempt_state("sealing"), attempt_state("ready"))
    add = local(tmp_path, b"abc")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert add.attempt_state == "ready"
    assert len(endpoint.sent) == 4


def test_a_late_answer_to_the_creation_of_an_empty_file_reads_the_attempt(
    tmp_path: Path,
) -> None:
    endpoint = Endpoint(httpx.ReadTimeout("late"), attempt_state("ready"))
    add = local(tmp_path, b"")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert (add.upload_id, add.attempt_state) == (U1, "ready")


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            httpx.Response(404, json={"code": "NOT_FOUND", "detail": "gone"}),
            "the service has no record of the upload of f.bin",
        ),
        (attempt_state("cancelled"), "the upload of f.bin is cancelled"),
    ],
)
def test_an_upload_that_is_gone_or_ended_says_so(
    tmp_path: Path, state: httpx.Response, message: str
) -> None:
    # The service forgot the sealed attempt of an earlier push, so the push starts a new one.
    forgotten = httpx.Response(404, json={"code": "NOT_FOUND", "detail": "gone"})
    endpoint = Endpoint(forgotten, created(), httpx.Response(504), state)
    add = resumable(tmp_path, b"abc", attempt_state="ready")
    saved: list[tuple[str | None, str | None]] = []
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload(
            "c1", add, lambda: saved.append((add.upload_id, add.attempt_state))
        )
    assert raised.value.message == message
    assert raised.value.hint == (
        "run `huron push` again. The next push starts a new upload of the file"
    )
    assert saved == [(None, None), (U1, None), (None, None)]
    assert (add.attempt_id, add.upload_id, add.attempt_state) == (None, None, None)
    assert len(endpoint.sent) == 4


def test_a_failed_attempt_says_why(tmp_path: Path) -> None:
    failure = {"code": "UPLOAD_SIZE_MISMATCH", "message": "the sizes differ"}
    endpoint = Endpoint(created(), httpx.Response(500), attempt_state("failed", failure))
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert raised.value.message == "the service did not seal f.bin: the sizes differ"
    assert raised.value.code == "UPLOAD_SIZE_MISMATCH"


def test_another_error_of_the_attempt_read_is_raised(tmp_path: Path) -> None:
    refused = httpx.Response(403, json={"code": "FORBIDDEN", "detail": "no"})
    endpoint = Endpoint(created(), httpx.Response(502), refused)
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)
    assert raised.value.code == "FORBIDDEN"


def test_the_fake_tusd_refuses_requests_without_the_tus_headers(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).drop_after = 2
    assert ready.run("push").exit_code == 1
    (add,) = stage(ready).adds
    assert add.upload_id is not None
    address = f"{TUS_URL}{add.upload_id}"
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


def test_a_dropped_chunk_reports_the_service_unreachable(tmp_path: Path) -> None:
    endpoint = Endpoint(created(), httpx.ConnectError("refused"))
    add = local(tmp_path, b"0123456789")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: None)
    assert raised.value.message == f"the upload service at {TUS_URL} is unreachable: refused"
    assert raised.value.hint == "run `huron push` again. The next push continues the upload"
    assert add.upload_id == U1


def resumable(tmp_path: Path, data: bytes, attempt_state: str | None = None) -> StagedAdd:
    """A staged add whose earlier push created the attempt ``a1`` with the upload :data:`U1`.

    ``attempt_state`` is the mark that the earlier push left on the attempt.
    """
    add = local(tmp_path, data)
    add.attempt_id, add.upload_id, add.attempt_state = "a1", U1, attempt_state
    return add


def test_a_resumed_upload_that_is_sealing_is_read_until_it_is_ready(tmp_path: Path) -> None:
    lines: list[str] = []
    endpoint = Endpoint(attempt_state("sealing"), attempt_state("sealing"), attempt_state("ready"))
    add = resumable(tmp_path, b"abc")
    uploader(endpoint, lines).upload("c1", add, lambda: None)
    assert (add.attempt_id, add.upload_id, add.attempt_state) == ("a1", U1, "ready")
    assert lines == ["uploaded f.bin (3 bytes)"]
    assert [request.url.path for request in endpoint.sent] == ["/api/v1/upload-attempts/a1"] * 3


def test_a_resumed_upload_that_ended_is_forgotten_with_its_mark(tmp_path: Path) -> None:
    endpoint = Endpoint(attempt_state("sealing"), attempt_state("cancelled"))
    add = resumable(tmp_path, b"abc", attempt_state="ready")
    saved: list[tuple[str | None, str | None, str | None]] = []
    with pytest.raises(CliError, match=r"the upload of f\.bin is cancelled"):
        uploader(endpoint, []).upload(
            "c1", add, lambda: saved.append((add.attempt_id, add.upload_id, add.attempt_state))
        )
    assert saved == [(None, None, None)]


def test_a_resumed_upload_whose_bytes_tusd_holds_reads_the_attempt(tmp_path: Path) -> None:
    head = httpx.Response(200, headers={"Upload-Offset": "3", "Upload-Length": "3"})
    endpoint = Endpoint(attempt_state("receiving"), head, attempt_state("ready"))
    add = resumable(tmp_path, b"abc")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert add.attempt_state == "ready"
    assert [request.method for request in endpoint.sent] == ["GET", "HEAD", "GET"]
