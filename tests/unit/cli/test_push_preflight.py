"""``huron push`` asks the service to check the commit before it uploads a byte."""

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from huron.core.lake.files.models import CommitRequest
from huron.core.storage import LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.support.lake import CONTRIBUTOR
from tests.unit.cli.conftest import make_collection

COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
ANSWERS = ["Run 7", "Solar wind run seven", *([False] * 7)]


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    """dave has created and checked out the active collection solar-wind.run7."""
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    seeded_cli.prompter.answers.extend(ANSWERS)
    seeded_cli.ok("create", "collection", "solar-wind.run7")
    make_collection(seeded_cli)
    return seeded_cli


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


def test_a_push_sends_a_dry_run_with_sizes_before_uploading(
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
    assert preview["adds"] == [{"rel_path": "a.txt", "size": 5}]
    assert preview["base_version"] == 3 and preview["message"] == "first"
    assert json.loads(real.content)["adds"][0]["sha256"]
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
    stage = ready.state.read_stage(ready.config_current())
    assert [add.rel_path for add in stage.adds] == ["a.txt"]
    assert stage.adds[0].sha256 is None


def test_a_base_version_conflict_is_reported_before_uploading(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    collection_id = uuid.UUID(ready.config_current())

    def someone_else_commits(_: httpx.Request) -> None:
        request = CommitRequest(3, (), (), "ws2")
        ready.loop.call(ready.runtime.lake.commits.commit(CONTRIBUTOR, collection_id, request))

    calls = list(share.calls)
    sent = watch(ready, someone_else_commits)
    conflict = ready.run("push")
    assert conflict.exit_code == 6 and "BASE_VERSION_CONFLICT" in conflict.stderr
    assert "huron pull" in conflict.stderr
    assert len(sent) == 1 and share.calls == calls and uploads(ready) == []
    assert share.stat(COLLECTION.joinpath("a.txt")) is None
    copy = ready.state.read_copy(str(collection_id))
    assert copy is not None and copy.version == 3


def test_a_push_behind_the_service_uploads_nothing(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    copy = ready.state.read_copy(ready.config_current())
    assert copy is not None
    ready.ok("unset", "override")
    ready.state.write_copy(copy)
    calls = list(share.calls)
    behind = ready.run("push")
    assert behind.exit_code == 6 and "huron pull" in behind.stderr
    assert share.calls == calls and uploads(ready) == []


def test_a_resumed_push_sends_the_hashes_it_already_knows(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    ready.ok("add", str(write(tmp_path, "a.txt", "alpha")))
    ready.router.fail_commits = "before"
    assert ready.run("push").exit_code == 1
    sent = watch(ready, lambda _: None)
    ready.ok("push")
    preview = json.loads(sent[0].content)
    assert preview["adds"][0]["size"] == 5 and len(preview["adds"][0]["sha256"]) == 64
