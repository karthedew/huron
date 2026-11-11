"""``huron push`` asks the service to check the commit before it uploads a byte."""

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from huron.core.storage import LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli

COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def uploads(cli: Cli) -> list[tuple[str, str]]:
    """The tus requests the CLI sent so far."""
    assert cli.tus is not None
    return list(cli.tus.requests)


def watch(cli: Cli, on_dry_run: Callable[[httpx.Request], None]) -> list[httpx.Request]:
    """Record the commits the CLI sends and call ``on_dry_run`` as each dry run goes out."""
    sent: list[httpx.Request] = []

    def observe(request: httpx.Request) -> None:
        if request.method == "POST" and request.url.path.endswith("/commits"):
            sent.append(request)
            if request.url.params.get("dry_run") == "true":
                on_dry_run(request)

    cli.router.observe = observe
    return sent


def test_a_push_sends_a_dry_run_with_the_recorded_sizes_and_hashes_before_uploading(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    uploaded_before: list[list[tuple[str, str]]] = []
    sent = watch(ready, lambda _: uploaded_before.append(uploads(ready)))
    assert "version 3 → 4" in ready.ok("push", "-m", "first").stdout
    assert uploaded_before == [[]] and uploads(ready)
    dry, real = sent
    assert dry.url.params["dry_run"] == "true" and "dry_run" not in real.url.params
    preview = json.loads(dry.content)
    alpha = hashlib.sha256(b"alpha").hexdigest()
    assert preview["adds"] == [{"rel_path": "a.txt", "size": 5, "sha256": alpha}]
    assert preview["base_version"] == 3 and preview["message"] == "first"
    assert "request_id" not in preview
    committed = json.loads(real.content)
    assert uuid.UUID(committed["request_id"])
    (add,) = committed["adds"]
    assert add["sha256"] == alpha and uuid.UUID(add["upload_id"])
    assert share.stat(COLLECTION.joinpath("a.txt")) is not None


def test_a_readers_push_is_refused_and_leaves_the_share_untouched(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.login_as("erin")
    ready.ok("checkout", "solar-wind.run7")
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    calls = list(share.calls)
    refused = ready.run("push")
    assert refused.exit_code == 4 and "FORBIDDEN" in refused.stderr
    assert share.calls == calls and share.stat(COLLECTION.joinpath("a.txt")) is None
    assert uploads(ready) == []
    stage = ready.working()
    assert [add.rel_path for add in stage.adds] == ["a.txt"]
    assert (stage.adds[0].attempt_id, stage.adds[0].upload_id) == (None, None)


def test_a_base_version_conflict_is_reported_before_uploading(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    collection_id = ready.config_current()

    def someone_else_commits(_: httpx.Request) -> None:
        ready.commit_nothing(collection_id, 3)

    calls = list(share.calls)
    sent = watch(ready, someone_else_commits)
    conflict = ready.run("push")
    assert conflict.exit_code == 6 and "BASE_VERSION_CONFLICT" in conflict.stderr
    assert "huron pull" in conflict.stderr
    assert len(sent) == 1 and share.calls == calls and uploads(ready) == []
    assert share.stat(COLLECTION.joinpath("a.txt")) is None
    assert ready.working().base_version == 3


def test_a_push_behind_the_service_uploads_nothing(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    version = ready.working().base_version
    ready.ok("unset", "override")
    ready.rebase(version)
    calls = list(share.calls)
    behind = ready.run("push")
    assert behind.exit_code == 6 and "huron pull" in behind.stderr
    assert share.calls == calls and uploads(ready) == []


def lose_the_commit(cli: Cli) -> None:
    """Drop the connection of the next commit before the service reads it."""
    cli.router.fail_commits = "before"


def drop_the_upload(cli: Cli) -> None:
    """Drop the connection of the next ``PATCH`` after three bytes, before the service seals it."""
    assert cli.tus is not None
    cli.tus.drop_after = 3


@pytest.mark.parametrize(
    ("stop", "sealed"),
    [(lose_the_commit, True), (drop_the_upload, False)],
    ids=["after the seal", "before the seal"],
)
def test_a_resumed_push_sends_the_known_hashes_and_the_sealed_uploads(
    ready: Cli, share: MemoryStorage, tmp_path: Path, stop: Callable[[Cli], None], sealed: bool
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    stop(ready)
    assert ready.run("push").exit_code == 1
    (stopped,) = ready.working().adds
    assert stopped.upload_id is not None
    sent = watch(ready, lambda _: None)
    ready.ok("push")
    (add,) = json.loads(sent[0].content)["adds"]
    assert add["size"] == 5 and len(add["sha256"]) == 64
    assert add.get("upload_id") == (stopped.upload_id if sealed else None)
