"""``huron push`` saves each commit before it sends it, and the next push reads its outcome.

The service saves the outcome of each request ID. The CLI asks for that outcome, or sends the
same request ID and body again when the service does not know the request. It never infers the
outcome from the version of the collection.
"""

import errno
import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.applications.cli import localstate
from huron.core.lake.publications.models import Resolution
from huron.core.storage import LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.support.lake import PLATFORM_ADMIN
from tests.unit.cli.conftest import ANSWERS

COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
PENDING = "the CLI did not get the result of the last commit of heliophysics.solar-wind.run7"
PENDING_HINT = "run `huron push` to get the result. Then run the command again"


class Killed(BaseException):
    """The end of the CLI process, as a kill ends it."""


def write(tmp_path: Path, name: str, data: bytes = b"alpha") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def is_commit(request: httpx.Request) -> bool:
    """A real commit of the push; its dry run is not one."""
    return (
        request.method == "POST"
        and request.url.path.endswith("/commits")
        and "dry_run" not in request.url.params
    )


def is_commit_traffic(request: httpx.Request) -> bool:
    """A commit, or a read of a commit request."""
    return is_commit(request) or request.url.path.startswith("/api/v1/commit-requests/")


def is_change(request: httpx.Request) -> bool:
    """A request that can change the service."""
    return request.method != "GET"


def watch(
    cli: Cli, matches: Callable[[httpx.Request], bool] = is_commit_traffic
) -> list[httpx.Request]:
    """The requests that ``matches`` that the CLI sends from now on: by default the commits and
    the reads of commit requests.
    """
    sent: list[httpx.Request] = []

    def observe(request: httpx.Request) -> None:
        if matches(request):
            sent.append(request)

    cli.router.observe = observe
    return sent


def recorded(cli: Cli) -> dict[str, str]:
    files = json.loads(cli.ok("-o", "json", "get", "files").stdout)
    return {item["rel_path"]: item["sha256"] for item in files}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stages_an_add(cli: Cli, tmp_path: Path) -> None:
    cli.ok("add", str(write(tmp_path, "a.txt")))


def leaves_a_pending_commit(cli: Cli, tmp_path: Path) -> None:
    """Stage ``a.txt`` and push it, but the commit does not reach the service."""
    stages_an_add(cli, tmp_path)
    cli.router.fail_commits = "before"
    assert cli.run("push").exit_code == 1


def stages_a_removal(cli: Cli, tmp_path: Path) -> None:
    cli.ok("add", str(write(tmp_path, "a.txt")))
    cli.ok("push")
    cli.ok("rm", "a.txt")


def unstages_during_the_upload(cli: Cli, tmp_path: Path) -> None:
    """Stage ``a.txt`` and unstage it as its bytes go, so the commit has no entry."""
    cli.ok("add", str(write(tmp_path, "a.txt")))
    forward = cli.router.tus
    assert forward is not None

    class UnstageOnPatch(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "PATCH":
                cli.router.tus = forward
                cli.ok("rm", "a.txt")
            return forward.handle_request(request)

    cli.router.tus = UnstageOnPatch()


KINDS = pytest.mark.parametrize(
    ("prepare", "summary"),
    [
        (stages_an_add, "+1 −0 files"),
        (stages_a_removal, "+0 −1 files"),
        (unstages_during_the_upload, "+0 −0 files"),
    ],
    ids=["an add", "a removal only", "an empty commit"],
)


@KINDS
def test_a_commit_lost_before_the_service_applied_it_is_sent_again_with_the_same_body(
    ready: Cli, tmp_path: Path, prepare: Callable[[Cli, Path], None], summary: str
) -> None:
    prepare(ready, tmp_path)
    before = ready.working().base_version
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    pending = ready.working().pending_commit
    assert pending is not None and pending.body["request_id"] == pending.request_id
    sent = watch(ready)
    pushed = ready.ok("push")
    assert f"version {before} → {before + 1}, {summary}" in pushed.stdout
    read, resent = sent
    assert (read.method, read.url.path) == ("GET", f"/api/v1/commit-requests/{pending.request_id}")
    assert is_commit(resent) and json.loads(resent.content) == pending.body
    after = ready.working()
    assert (after.empty, after.pending_commit, after.base_version) == (True, None, before + 1)


@KINDS
def test_a_commit_whose_answer_was_lost_after_the_service_applied_it_is_not_sent_again(
    ready: Cli, tmp_path: Path, prepare: Callable[[Cli, Path], None], summary: str
) -> None:
    prepare(ready, tmp_path)
    before = ready.working().base_version
    ready.router.fail_commits = "after"
    assert ready.run("push").exit_code == 1
    assert ready.working().pending_commit is not None
    sent = watch(ready)
    pushed = ready.ok("push")
    assert f"version {before} → {before + 1}, {summary}" in pushed.stdout
    assert [request.method for request in sent] == ["GET"]
    after = ready.working()
    assert (after.empty, after.pending_commit, after.base_version) == (True, None, before + 1)


def test_a_commit_refused_on_its_retry_keeps_the_stage_after_another_user_committed(
    ready: Cli, tmp_path: Path
) -> None:
    stages_an_add(ready, tmp_path)
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    ready.commit_nothing(ready.config_current(), 3)
    waiting = ready.working()
    assert [add.rel_path for add in waiting.adds] == ["a.txt"]
    assert waiting.pending_commit is not None
    refused = ready.run("push")
    assert refused.exit_code == 6 and "[BASE_VERSION_CONFLICT]" in refused.stderr
    after = ready.working()
    assert after.pending_commit is None and after.base_version == 3
    (add,) = after.adds
    assert add.attempt_state == "ready"
    ready.ok("pull")
    assert "version 4 → 5, +1 −0 files" in ready.ok("push").stdout
    assert recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_commit_applied_before_another_users_commit_sets_its_own_version_as_the_base(
    ready: Cli, tmp_path: Path
) -> None:
    stages_an_add(ready, tmp_path)
    ready.router.fail_commits = "after"
    assert ready.run("push").exit_code == 1
    ready.commit_nothing(ready.config_current(), 4)
    waiting = ready.working()
    assert [add.rel_path for add in waiting.adds] == ["a.txt"]
    assert (waiting.base_version, waiting.pending_commit is not None) == (3, True)
    assert "version 3 → 4, +1 −0 files" in ready.ok("push").stdout
    after = ready.working()
    assert (after.empty, after.pending_commit, after.base_version) == (True, None, 4)
    status = json.loads(ready.ok("-o", "json", "status").stdout)
    assert (status["service_version"], status["behind"]) == (5, True)


def test_a_refusal_saved_while_the_answer_was_lost_clears_the_pending_commit(
    ready: Cli, tmp_path: Path
) -> None:
    stages_an_add(ready, tmp_path)
    collection_id = ready.config_current()

    def someone_else_commits(request: httpx.Request) -> None:
        if is_commit(request):
            ready.router.observe = None
            ready.commit_nothing(collection_id, 3)

    ready.router.observe = someone_else_commits
    ready.router.fail_commits = "after"
    assert ready.run("push").exit_code == 1
    assert ready.working().pending_commit is not None
    sent = watch(ready)
    refused = ready.run("push")
    assert refused.exit_code == 6 and "[BASE_VERSION_CONFLICT]" in refused.stderr
    assert [request.method for request in sent] == ["GET"]
    after = ready.working()
    assert after.pending_commit is None and [add.rel_path for add in after.adds] == ["a.txt"]


def kill_on_the_commit(cli: Cli) -> None:
    """End the CLI as it is about to send its commit."""

    def kill(request: httpx.Request) -> None:
        if is_commit(request):
            cli.router.observe = None
            raise Killed

    cli.router.observe = kill


def kill_after_the_commit(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> list[httpx.Response]:
    """End the CLI when the answer of its commit arrives; the answers it got."""
    forward = cli.router.handle_request
    answers: list[httpx.Response] = []

    def handle(request: httpx.Request) -> httpx.Response:
        response = forward(request)
        if is_commit(request) and not answers:
            answers.append(response)
            raise Killed
        return response

    monkeypatch.setattr(cli.router, "handle_request", handle)
    return answers


def writes_after_the_commit(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, *, kill: bool
) -> list[dict[str, Any]]:
    """The documents of the state writes after the answer of the commit arrives; with ``kill``,
    the first of them ends the CLI before it writes.
    """
    forward = cli.router.handle_request
    answered: list[httpx.Response] = []
    documents: list[dict[str, Any]] = []
    write_atomically = localstate.write_atomically

    def handle(request: httpx.Request) -> httpx.Response:
        response = forward(request)
        if is_commit(request):
            answered.append(response)
        return response

    def recording(path: Path, data: bytes) -> None:
        if answered and path.name == "working.json":
            documents.append(json.loads(data))
            if kill:
                monkeypatch.setattr(localstate, "write_atomically", write_atomically)
                raise Killed
        write_atomically(path, data)

    monkeypatch.setattr(cli.router, "handle_request", handle)
    monkeypatch.setattr(localstate, "write_atomically", recording)
    return documents


def test_a_kill_before_the_send_leaves_a_commit_that_the_next_push_sends(
    ready: Cli, tmp_path: Path
) -> None:
    stages_an_add(ready, tmp_path)
    kill_on_the_commit(ready)
    with pytest.raises(Killed):
        ready.run("push")
    pending = ready.working().pending_commit
    assert pending is not None
    sent = watch(ready)
    assert "version 3 → 4" in ready.ok("push").stdout
    assert [request.method for request in sent] == ["GET", "POST"]
    assert json.loads(sent[1].content) == pending.body
    assert ready.working().empty


def test_a_kill_after_the_send_leaves_a_commit_whose_outcome_the_next_push_reads(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages_an_add(ready, tmp_path)
    answers = kill_after_the_commit(ready, monkeypatch)
    with pytest.raises(Killed):
        ready.run("push")
    monkeypatch.undo()
    assert [answer.status_code for answer in answers] == [200]
    assert ready.working().pending_commit is not None
    sent = watch(ready)
    assert "version 3 → 4" in ready.ok("push").stdout
    assert [request.method for request in sent] == ["GET"]
    assert ready.working().empty and recorded(ready) == {"a.txt": sha(b"alpha")}


def test_a_kill_before_the_state_write_of_a_success_is_finished_by_the_next_push(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages_an_add(ready, tmp_path)
    writes_after_the_commit(ready, monkeypatch, kill=True)
    with pytest.raises(Killed):
        ready.run("push")
    monkeypatch.undo()
    stopped = ready.working()
    assert stopped.pending_commit is not None and stopped.base_version == 3
    sent = watch(ready)
    assert "version 3 → 4" in ready.ok("push").stdout
    assert [request.method for request in sent] == ["GET"]
    after = ready.working()
    assert (after.empty, after.pending_commit, after.base_version) == (True, None, 4)


def test_a_success_sets_the_base_and_clears_the_stage_and_the_pending_commit_in_one_write(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages_an_add(ready, tmp_path)
    ready.ok("add", str(write(tmp_path, "b.txt")))
    documents = writes_after_the_commit(ready, monkeypatch, kill=False)
    ready.ok("push")
    (document,) = documents
    assert (document["base_version"], document["pending_commit"]) == (4, None)
    assert (document["adds"], document["removes"]) == ([], [])


@pytest.mark.parametrize(
    "argv",
    [("add", "{tmp}/b.txt"), ("rm", "a.txt"), ("pull",), ("checkout", "solar-wind.run7")],
    ids=["add", "rm", "pull", "checkout"],
)
def test_a_pending_commit_refuses_the_commands_that_change_the_working_copy(
    ready: Cli, tmp_path: Path, argv: tuple[str, ...]
) -> None:
    stages_an_add(ready, tmp_path)
    write(tmp_path, "b.txt")
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    path = ready.state.root / "collections" / ready.config_current() / "working.json"
    before = path.read_bytes()
    refused = ready.run(*(part.format(tmp=tmp_path) for part in argv))
    assert refused.exit_code == 6
    assert f"error: {PENDING}" in refused.stderr and f"hint: {PENDING_HINT}" in refused.stderr
    assert path.read_bytes() == before


def test_a_pending_commit_keeps_its_working_copy_current_and_refuses_its_checkout(
    ready: Cli, tmp_path: Path
) -> None:
    run7 = ready.config_current()
    ready.prompter.answers.extend(ANSWERS)
    ready.ok("create", "collection", "solar-wind.run8")
    run8 = ready.config_current()
    ready.ok("checkout", "solar-wind.run7")
    stages_an_add(ready, tmp_path)
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    leaving = ready.run("checkout", "solar-wind.run8")
    assert leaving.exit_code == 6 and PENDING in leaving.stderr
    assert ready.config_current() == run7
    ready.configure(current_collection=run8)
    returning = ready.run("checkout", "solar-wind.run7")
    assert returning.exit_code == 6 and PENDING in returning.stderr
    assert ready.state.working(run7) is not None
    assert ready.config_current() == run8


def as_it_is(cli: Cli) -> None:
    """Prepare nothing."""


def drafts_run8(cli: Cli) -> None:
    """Reserve the draft solar-wind.run8, then check out solar-wind.run7 again."""
    cli.prompter.answers.extend(ANSWERS)
    cli.ok("create", "collection", "solar-wind.run8", "--draft")
    cli.ok("checkout", "solar-wind.run7")


@pytest.mark.parametrize(
    ("prepare", "argv"),
    [
        (as_it_is, ("create", "collection", "solar-wind.run8", "--draft")),
        (as_it_is, ("create", "collection", "solar-wind.run8")),
        (drafts_run8, ("activate", "collection", "solar-wind.run8")),
        (as_it_is, ("unset", "override")),
    ],
    ids=["create a draft", "create and activate", "activate", "change the collection"],
)
def test_a_pending_commit_refuses_a_change_that_checks_out_before_the_service_gets_it(
    ready: Cli, tmp_path: Path, prepare: Callable[[Cli], None], argv: tuple[str, ...]
) -> None:
    prepare(ready)
    leaves_a_pending_commit(ready, tmp_path)
    selected = ready.config_current()
    changes = watch(ready, is_change)
    refused = ready.run(*argv)
    assert refused.exit_code == 6
    assert f"error: {PENDING}" in refused.stderr and f"hint: {PENDING_HINT}" in refused.stderr
    assert changes == [] and ready.config_current() == selected


def test_a_pending_commit_lets_a_change_that_checks_out_nothing_go_to_the_service(
    ready: Cli, tmp_path: Path
) -> None:
    leaves_a_pending_commit(ready, tmp_path)
    ready.rebase(2)
    changes = watch(ready, is_change)
    ready.ok("unset", "override")
    assert [request.method for request in changes] == ["PATCH"]
    working = ready.working()
    assert working.base_version == 2 and working.pending_commit is not None


def holds_the_commit(share: MemoryStorage) -> None:
    """Make the publication fail on the lake one time, so that the commit stays accepted."""
    share.faults[("fsync", COLLECTION)] = errno.EIO


def blocks_the_commit(share: MemoryStorage) -> None:
    """Put a file that the commit does not expect at ``a.txt``, so that the commit is blocked."""
    share.write_bytes(COLLECTION.joinpath("a.txt"), b"stray", 0o644)


def answers_each_read(cli: Cli) -> None:
    """Let the service answer each read of the commit request at once."""


def times_out_the_last_read(cli: Cli) -> None:
    """The first read of the commit request takes 585 seconds. The next read gets no answer
    before its timeout.
    """
    reads: list[httpx.Request] = []

    def observe(request: httpx.Request) -> None:
        if not request.url.path.startswith("/api/v1/commit-requests/"):
            return
        reads.append(request)
        if len(reads) == 1:
            cli.monotonic.advance(585.0)
            return
        cli.monotonic.advance(request.extensions["timeout"]["read"])
        raise httpx.ReadTimeout("the answer is late", request=request)

    cli.router.observe = observe


@pytest.mark.parametrize(
    ("hold", "exit_code", "error", "hint"),
    [
        (
            holds_the_commit,
            1,
            "the service accepted the commit, but did not finish it in 600 seconds",
            "to get the result, run `huron push`",
        ),
        (
            blocks_the_commit,
            6,
            "the service accepted the commit, but a step of it is blocked [PUBLICATION_BLOCKED]",
            "a platform administrator must resolve the commit request."
            " To get the result, run `huron push`",
        ),
    ],
    ids=["accepted", "blocked"],
)
@pytest.mark.parametrize(
    "reads", [answers_each_read, times_out_the_last_read], ids=["answered", "a late last read"]
)
def test_a_commit_unfinished_at_the_deadline_keeps_the_pending_commit_and_the_stage(
    ready: Cli,
    share: MemoryStorage,
    tmp_path: Path,
    hold: Callable[[MemoryStorage], None],
    exit_code: int,
    error: str,
    hint: str,
    reads: Callable[[Cli], None],
) -> None:
    stages_an_add(ready, tmp_path)
    hold(share)
    reads(ready)
    start = ready.monotonic.now
    pushed = ready.run("push")
    assert pushed.exit_code == exit_code
    assert pushed.stderr.endswith(f"error: {error}\nhint: {hint}\n")
    assert ready.monotonic.now - start == 600.0
    waiting = ready.working()
    assert waiting.pending_commit is not None and [a.rel_path for a in waiting.adds] == ["a.txt"]


def test_a_blocked_commit_is_kept_until_the_service_ends_it(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    stages_an_add(ready, tmp_path)
    blocks_the_commit(share)
    assert ready.run("push").exit_code == 6
    collection_id = uuid.UUID(ready.config_current())
    ready.loop.call(
        ready.runtime.publications.resolve(PLATFORM_ADMIN, collection_id, Resolution.ABANDON)
    )
    abandoned = ready.run("push")
    assert abandoned.exit_code == 6
    assert "a platform administrator abandoned the commit" in abandoned.stderr
    after = ready.working()
    assert after.pending_commit is None and after.adds[0].attempt_state == "ready"
    share.remove_file(COLLECTION.joinpath("a.txt"))
    assert "version 3 → 4, +1 −0 files" in ready.ok("push").stdout
    assert share.read_bytes(COLLECTION.joinpath("a.txt")) == b"alpha"


def stage_removals(cli: Cli, entries: int) -> None:
    with cli.state.changing(cli.config_current()) as working:
        working.removes = [f"f{index:05}.txt" for index in range(entries)]


def test_a_stage_of_more_than_10000_entries_is_refused_before_any_request(ready: Cli) -> None:
    stage_removals(ready, 10_001)
    sent = watch(ready)
    pushed = ready.run("push")
    assert pushed.exit_code == 7
    assert pushed.stderr == (
        "error: the stage holds 10,001 changes. A push can send at most 10,000 changes\n"
        "hint: push the changes in parts. To unstage a path, run `huron rm <path>`."
        " Stage the path again after the push\n"
    )
    assert sent == [] and ready.working().pending_commit is None


def test_a_stage_of_10000_entries_goes_to_the_service(ready: Cli) -> None:
    stage_removals(ready, 10_000)
    pushed = ready.run("push")
    assert pushed.exit_code == 7 and "[FILE_NOT_RECORDED]" in pushed.stderr


def fail_once(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, matches: Callable[[httpx.Request], bool]
) -> None:
    """Answer the next request that ``matches`` with a server error, before the service sees it."""
    forward = cli.router.handle_request
    failed: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if matches(request) and not failed:
            failed.append(request)
            problem = {
                "code": "LAKE_UNAVAILABLE",
                "detail": "the lake is not mounted",
                "status": 503,
            }
            return httpx.Response(503, json=problem)
        return forward(request)

    monkeypatch.setattr(cli.router, "handle_request", handle)


def test_a_server_error_of_the_commit_keeps_the_pending_commit(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages_an_add(ready, tmp_path)
    fail_once(ready, monkeypatch, is_commit)
    failed = ready.run("push")
    assert failed.exit_code == 1 and "[LAKE_UNAVAILABLE]" in failed.stderr
    assert ready.working().pending_commit is not None
    sent = watch(ready)
    assert "version 3 → 4" in ready.ok("push").stdout
    assert [request.method for request in sent] == ["GET", "POST"]


def test_a_server_error_of_the_status_read_keeps_the_pending_commit(
    ready: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages_an_add(ready, tmp_path)
    ready.router.fail_commits = "after"
    assert ready.run("push").exit_code == 1
    fail_once(
        ready, monkeypatch, lambda request: request.url.path.startswith("/api/v1/commit-requests/")
    )
    failed = ready.run("push")
    assert failed.exit_code == 1 and "[LAKE_UNAVAILABLE]" in failed.stderr
    assert ready.working().pending_commit is not None
    assert "version 3 → 4" in ready.ok("push").stdout
    assert ready.working().pending_commit is None
