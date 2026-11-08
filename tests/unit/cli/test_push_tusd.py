"""``huron push`` uploads each staged file through tusd and commits the receipts."""

import hashlib
import io
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import CliError
from huron.applications.cli.state import Stage, StagedAdd
from huron.applications.cli.uploads import Uploader, UploadService
from huron.core.lake.files.models import CommitRequest
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.support.lake import CONTRIBUTOR
from tests.support.tus import TUS_URL, FakeTus
from tests.unit.cli.conftest import PREFIX

COLLECTION = PREFIX / "helio" / "heliophysics" / "solar-wind" / "run7"
ANSWERS = ["Run 7", "Solar wind run seven", *([False] * 7)]
#: The service's hook timeout here: three reads of a pending upload, five seconds apart.
HOOK_TIMEOUT = 10


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """The CLI over a service that holds ``share`` as its lake and takes uploads of 1000 bytes."""
    running = Cli(
        tmp_path,
        lambda config: share,
        PREFIX,
        lake=share,
        upload_hook_timeout=timedelta(seconds=HOOK_TIMEOUT),
        upload_max_size=1000,
    )
    yield running
    running.close()


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    """dave has created and checked out the active collection solar-wind.run7."""
    seeded_cli.login_as("carol")
    seeded_cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    seeded_cli.prompter.answers.extend(ANSWERS)
    seeded_cli.ok("create", "collection", "solar-wind.run7")
    return seeded_cli


def tus(cli: Cli) -> FakeTus:
    assert cli.tus is not None
    return cli.tus


def stage(cli: Cli) -> Stage:
    return cli.state.read_stage(cli.config_current())


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


def test_a_push_uploads_through_tusd_and_commits_the_receipt(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    pushed = ready.ok("push", "-m", "first")
    assert "version 3 → 4, +1 −0 files" in pushed.stdout
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION / "a.txt") == b"alpha"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}
    assert stage(ready).empty


def test_an_empty_file_finishes_in_the_creation_request(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "empty.txt", b"")
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST"]
    assert share.read_bytes(COLLECTION / "empty.txt") == b""
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
    assert add.upload_id is not None and add.upload_url == f"{TUS_URL}{add.upload_id}"
    assert tus(ready).uploads[add.upload_id].offset == 3
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD", "PATCH"]
    assert share.read_bytes(COLLECTION / "a.txt") == b"alphabet"
    assert recorded(ready) == {"a.txt": sha(b"alphabet")}


def test_an_upload_that_tusd_lost_starts_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alphabet")
    tus(ready).drop_after = 3
    assert ready.run("push").exit_code == 1
    tus(ready).uploads.clear()
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD", "POST", "PATCH"]
    assert share.read_bytes(COLLECTION / "a.txt") == b"alphabet"


def test_an_upload_unknown_to_the_service_starts_again(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    current = stage(ready)
    unknown = str(uuid.uuid4())
    current.adds[0].upload_id, current.adds[0].upload_url = unknown, f"{TUS_URL}{unknown}"
    ready.state.write_stage(ready.config_current(), current)
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]


def test_an_upload_id_the_service_refuses_is_reported(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    current = stage(ready)
    current.adds[0].upload_id, current.adds[0].upload_url = "nope", f"{TUS_URL}nope"
    ready.state.write_stage(ready.config_current(), current)
    refused = ready.run("push")
    assert refused.exit_code == 7 and "REQUEST_INVALID" in refused.stderr
    assert tus(ready).requests == []


def test_a_hash_mismatch_commits_nothing(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).corrupt = True
    mismatch = ready.run("push")
    assert mismatch.exit_code == 8
    assert "the service hash of a.txt is not the same as the local hash" in mismatch.stderr
    assert recorded(ready) == {}
    assert stage(ready).adds[0].sha256 is None


@pytest.mark.parametrize("status", [500, 502, 504])
def test_an_unclear_final_answer_reads_the_placed_upload(
    ready: Cli, share: MemoryStorage, tmp_path: Path, status: int
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).finish_status = status
    pushed = ready.ok("push")
    assert "uploaded a.txt (5 bytes)" in pushed.stderr
    assert share.read_bytes(COLLECTION / "a.txt") == b"alpha"
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


@pytest.mark.parametrize("status", [504, None])
def test_a_pending_upload_is_not_placed_and_the_next_push_starts_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path, status: int | None
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).finish_status, tus(ready).skip_finish = status, True
    pending = ready.run("push")
    assert pending.exit_code == 8
    assert f"the service did not place a.txt in {HOOK_TIMEOUT} seconds" in pending.stderr
    assert "The next push starts a new upload of the file" in pending.stderr
    assert ready.slept == [5.0, 5.0]
    (add,) = stage(ready).adds
    assert (add.upload_id, add.upload_url, add.sha256) == (None, None, None)
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_failed_upload_prints_the_failure(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    saved = {
        path: node for path, node in share.nodes.items() if COLLECTION in (path, *path.parents)
    }
    for path in saved:
        del share.nodes[path]
    failed = ready.run("push")
    assert failed.exit_code == 8 and "[STORAGE_FAILED]" in failed.stderr
    assert "the service did not place a.txt: the collection directory" in failed.stderr
    share.nodes.update(saved)
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION / "a.txt") == b"alpha"


@pytest.mark.parametrize(
    ("method", "status", "exit_code", "message"),
    [
        ("POST", 401, 3, "the upload proxy did not accept your token"),
        ("PATCH", 403, 4, "this upload belongs to another user, or it no longer exists"),
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


def test_a_retried_push_skips_the_placed_uploads(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    staged(ready, tmp_path, "b.txt", b"bravo")
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    assert all(add.sha256 is not None for add in stage(ready).adds)
    tus(ready).requests.clear()
    retried = ready.ok("push")
    assert tus(ready).requests == []
    assert "a.txt is on the service from an earlier push" in retried.stderr
    assert recorded(ready) == {"a.txt": sha(b"alpha"), "b.txt": sha(b"bravo")}


def test_a_file_changed_after_its_upload_is_uploaded_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    source = staged(ready, tmp_path, "a.txt", b"alpha")
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    source.write_bytes(b"bravo")
    tus(ready).requests.clear()
    ready.ok("push")
    assert [method for method, _ in tus(ready).requests] == ["POST", "PATCH"]
    assert share.read_bytes(COLLECTION / "a.txt") == b"bravo"
    assert recorded(ready) == {"a.txt": sha(b"bravo")}


def test_a_file_that_changed_size_after_add_is_refused(ready: Cli, tmp_path: Path) -> None:
    source = staged(ready, tmp_path, "a.txt", b"alpha")
    source.write_bytes(b"longer")
    refused = ready.run("push")
    assert refused.exit_code == 2 and "changed after you staged it" in refused.stderr
    assert f"run `huron add {source}`" in refused.stderr
    assert tus(ready).requests == []


def test_a_file_removed_after_add_is_refused(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha").unlink()
    refused = ready.run("push")
    assert refused.exit_code == 2 and "changed after you staged it" in refused.stderr


def test_an_upload_whose_bytes_all_arrived_is_read_from_the_service(
    ready: Cli, tmp_path: Path
) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).drop_after = 5
    assert ready.run("push").exit_code == 1
    tus(ready).requests.clear()
    pending = ready.run("push")
    assert [method for method, _ in tus(ready).requests] == ["HEAD"]
    assert pending.exit_code == 8 and "did not place a.txt" in pending.stderr


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
    source = tmp_path / "f.bin"
    source.write_bytes(data)
    return StagedAdd("f.bin", str(source), len(data))


def created(upload_id: str = "u1") -> httpx.Response:
    return httpx.Response(201, headers={"Location": f"/files/{upload_id}"})


def test_the_uploader_sends_chunks_with_a_progress_line(tmp_path: Path) -> None:
    lines: list[str] = []
    data = b"0123456789"
    receipt = {"Huron-Sha256": sha(data)}
    endpoint = Endpoint(
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        httpx.Response(204, headers={"Upload-Offset": "10", **receipt}),
    )
    add = local(tmp_path, data)
    saved: list[str | None] = []
    uploader(endpoint, lines).upload("c1", add, lambda: saved.append(add.upload_url))
    assert lines == [
        "sent 4 of 10 bytes of f.bin",
        "sent 8 of 10 bytes of f.bin",
        "uploaded f.bin (10 bytes)",
    ]
    assert (add.upload_url, add.upload_id, add.sha256) == (f"{TUS_URL}u1", "u1", sha(data))
    assert saved == [f"{TUS_URL}u1"]
    offsets = [request.headers["Upload-Offset"] for request in endpoint.sent[1:]]
    assert offsets == ["0", "4", "8"]
    creation = endpoint.sent[0]
    assert creation.headers["Tus-Resumable"] == "1.0.0"
    assert creation.headers["Authorization"] == "Bearer token"
    assert creation.headers["Upload-Metadata"] == "collection YzE=,rel_path Zi5iaW4="


def test_the_uploader_refuses_a_creation_without_an_address(tmp_path: Path) -> None:
    endpoint = Endpoint(httpx.Response(201))
    with pytest.raises(CliError, match="did not give an upload address"):
        uploader(endpoint, []).upload("c1", local(tmp_path, b"abc"), lambda: None)


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


def test_a_commit_refused_after_the_uploads_keeps_the_receipts(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    collection_id = uuid.UUID(ready.config_current())

    def someone_else_commits(request: httpx.Request) -> None:
        if request.url.path.endswith("/commits") and "dry_run" not in request.url.params:
            change = CommitRequest(3, (), (), "ws2")
            ready.loop.call(ready.runtime.lake.commits.commit(CONTRIBUTOR, collection_id, change))

    ready.router.observe = someone_else_commits
    refused = ready.run("push")
    assert refused.exit_code == 6 and "BASE_VERSION_CONFLICT" in refused.stderr
    assert stage(ready).adds[0].sha256 == sha(b"alpha")


def read_timeout(request: httpx.Request) -> float | None:
    timeout: dict[str, float | None] = request.extensions["timeout"]
    return timeout["read"]


def upload_state(state: str, sha256: str | None = None) -> httpx.Response:
    """The API's answer to ``GET /api/v1/uploads/u1``."""
    body = {"id": "u1", "state": state, "sha256": sha256, "failure": None}
    return httpx.Response(200, json=body)


def test_the_request_that_finishes_an_upload_waits_for_the_hook(tmp_path: Path) -> None:
    data = b"0123456789"
    endpoint = Endpoint(
        created(),
        httpx.Response(204, headers={"Upload-Offset": "4"}),
        httpx.Response(204, headers={"Upload-Offset": "8"}),
        httpx.Response(204, headers={"Upload-Offset": "10", "Huron-Sha256": sha(data)}),
    )
    uploader(endpoint, []).upload("c1", local(tmp_path, data), lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [5.0, 5.0, 5.0, 70.0]


def test_the_creation_of_an_empty_file_waits_for_the_hook(tmp_path: Path) -> None:
    finished = httpx.Response(201, headers={"Location": "/files/u1", "Huron-Sha256": sha(b"")})
    endpoint = Endpoint(finished)
    add = local(tmp_path, b"")
    uploader(endpoint, []).upload("c1", add, lambda: None)
    assert [read_timeout(request) for request in endpoint.sent] == [70.0]
    assert add.sha256 == sha(b"")


def test_a_late_final_answer_reads_the_placed_upload(tmp_path: Path) -> None:
    lines: list[str] = []
    data = b"abc"
    endpoint = Endpoint(created(), httpx.ReadTimeout("late"), upload_state("placed", sha(data)))
    add = local(tmp_path, data)
    uploader(endpoint, lines).upload("c1", add, lambda: None)
    assert add.sha256 == sha(data) and lines == ["uploaded f.bin (3 bytes)"]
    assert endpoint.sent[-1].url.path == "/api/v1/uploads/u1"


def test_a_late_answer_to_the_creation_of_an_empty_file_starts_again(tmp_path: Path) -> None:
    endpoint = Endpoint(httpx.ReadTimeout("late"))
    add = local(tmp_path, b"")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: None)
    assert raised.value.message == (
        "the upload service did not answer the creation of f.bin in time"
    )
    assert raised.value.hint is not None and "starts a new upload" in raised.value.hint
    assert add.upload_id is None


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            httpx.Response(404, json={"code": "UPLOAD_NOT_FOUND", "detail": "gone"}),
            "the service has no record of the upload of f.bin",
        ),
        (upload_state("terminated"), "the upload of f.bin is terminated"),
    ],
)
def test_an_upload_that_is_gone_or_terminated_says_so(
    tmp_path: Path, state: httpx.Response, message: str
) -> None:
    endpoint = Endpoint(created(), httpx.Response(504), state)
    add = local(tmp_path, b"abc")
    saved: list[str | None] = []
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: saved.append(add.upload_id))
    assert raised.value.message == message
    assert raised.value.hint == (
        "run `huron push` again. The next push starts a new upload of the file"
    )
    assert saved == ["u1", None]
    assert len(endpoint.sent) == 3


def test_the_fake_tusd_refuses_requests_without_the_tus_headers(ready: Cli, tmp_path: Path) -> None:
    staged(ready, tmp_path, "a.txt", b"alpha")
    tus(ready).drop_after = 2
    assert ready.run("push").exit_code == 1
    (add,) = stage(ready).adds
    assert add.upload_url is not None
    tokens = ready.state.read_tokens()
    assert tokens is not None
    bearer = {"Authorization": f"Bearer {tokens.huron_token}"}
    tus_headers = {**bearer, "Tus-Resumable": "1.0.0"}

    def answer(method: str, url: str, headers: dict[str, str], content: bytes = b"") -> int:
        request = httpx.Request(method, url, headers=headers, content=content)
        return tus(ready).handle(request).status_code

    assert answer("POST", TUS_URL, {**bearer, "Upload-Length": "1"}) == 412
    assert answer("HEAD", add.upload_url, bearer) == 412
    assert answer("HEAD", add.upload_url, {**bearer, "Tus-Resumable": "0.2.2"}) == 412
    patch = {**tus_headers, "Upload-Offset": "2"}
    assert answer("PATCH", add.upload_url, patch, b"pha") == 415
    stream = {**patch, "Content-Type": "application/offset+octet-stream"}
    assert answer("PATCH", add.upload_url, {**stream, "Tus-Resumable": ""}, b"pha") == 412
    assert answer("HEAD", add.upload_url, tus_headers) == 200


def test_a_dropped_chunk_reports_the_service_unreachable(tmp_path: Path) -> None:
    endpoint = Endpoint(created(), httpx.ConnectError("refused"))
    add = local(tmp_path, b"0123456789")
    with pytest.raises(CliError) as raised:
        uploader(endpoint, []).upload("c1", add, lambda: None)
    assert raised.value.message == f"the upload service at {TUS_URL} is unreachable: refused"
    assert raised.value.hint == "run `huron push` again. The next push continues the upload"
    assert add.upload_id == "u1"
