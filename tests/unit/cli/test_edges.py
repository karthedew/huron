"""Edge paths of the CLI: entry point, prompts and failure branches."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from huron.applications.cli import main as entry
from huron.applications.cli.errors import CliError
from huron.applications.cli.login import Oidc
from huron.applications.cli.prompts import QuestionaryPrompter
from huron.core.storage import LakePath
from huron.core.storage.memory import MemoryStorage
from tests.fakes.issuer import ISSUER, FakeIssuer
from tests.support.cli import Cli
from tests.unit.cli.conftest import PREFIX, make_collection
from tests.unit.cli.test_collections import BASE_ANSWERS


class Answer:
    def __init__(self, value: object) -> None:
        self.value = value

    def ask(self) -> object:
        return self.value


def test_main_runs_the_cli_and_refuses_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["huron", "config", "show"])
    with pytest.raises(SystemExit) as done:
        entry.main()
    assert done.value.code == 0
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(SystemExit) as refused:
        entry.main()
    assert refused.value.code == 1


def test_questionary_prompter(monkeypatch: pytest.MonkeyPatch) -> None:
    import questionary

    seen: dict[str, object] = {}

    def text(message: str, default: str, validate: object) -> Answer:
        seen["validate"] = validate
        return Answer("typed")

    monkeypatch.setattr(questionary, "text", text)
    monkeypatch.setattr(questionary, "select", lambda *a, **k: Answer("b"))
    monkeypatch.setattr(questionary, "confirm", lambda *a, **k: Answer(True))
    prompter = QuestionaryPrompter()
    assert prompter.text("q", validate=lambda v: "bad" if v == "x" else None) == "typed"
    checker = seen["validate"]
    assert checker("x") == "bad" and checker("ok") is True  # type: ignore[operator]
    assert prompter.text("q") == "typed"
    assert prompter.select("q", ["a", "b"]) == "b"
    assert prompter.confirm("q") is True
    for name in ("text", "select", "confirm"):
        monkeypatch.setattr(questionary, name, lambda *a, **k: Answer(None))
    with pytest.raises(CliError):
        prompter.text("q")
    with pytest.raises(CliError):
        prompter.confirm("q")


def oidc(handler) -> Oidc:  # type: ignore[no-untyped-def]
    return Oidc(httpx.Client(transport=httpx.MockTransport(handler)), ISSUER, "huron-cli")


def test_provider_failures() -> None:
    issuer = FakeIssuer()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(CliError, match="unreachable"):
        oidc(down).discovery()

    def no_id_token(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=issuer.discovery())
        if request.url.path.endswith("/device"):
            return issuer.handler(request)
        return httpx.Response(200, json={"access_token": "x"})

    with pytest.raises(CliError, match="no ID token"):
        oidc(no_id_token).device_flow(lambda u, c: None, lambda s: None)
    assert oidc(no_id_token).refresh("r") is None


def test_loopback_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    from urllib.parse import parse_qs, urlsplit

    from huron.applications.cli import login

    issuer = FakeIssuer()
    client = oidc(issuer.handler)

    def browser(url: str) -> None:
        query = parse_qs(urlsplit(url).query)
        params = {"code": "unknown", "state": query["state"][0]}
        threading.Thread(
            target=lambda: httpx.get(query["redirect_uri"][0], params=params), daemon=True
        ).start()

    with pytest.raises(CliError, match="invalid_grant"):
        client.loopback_flow(browser)
    monkeypatch.setattr(login, "_LOOPBACK_TIMEOUT", 0.05)
    with pytest.raises(CliError, match="did not answer in time"):
        client.loopback_flow(lambda url: None)


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    return seeded_cli


def test_push_and_status_edge_cases(ready: Cli, share: MemoryStorage, tmp_path: Path) -> None:
    ready.prompter.answers.extend(BASE_ANSWERS)
    ready.ok("create", "collection", "solar-wind.draft", "--draft")
    status = json.loads(ready.ok("-o", "json", "status").stdout)
    assert status["unrecorded"] == []
    source = tmp_path / "a.txt"
    source.write_text("a")
    ready.ok("add", str(source))
    assert ready.run("push").exit_code == 6
    ready.ok("activate", "collection")
    make_collection(ready, "draft")
    ready.ok("add", str(source))
    ready.ok("push")
    ready.configure(mount_prefix="/elsewhere")
    assert json.loads(ready.ok("-o", "json", "status").stdout)["unrecorded"] is None
    ready.configure(mount_prefix=str(PREFIX))
    ready.ok("rm", "a.txt")
    target = LakePath.of("helio", "heliophysics", "solar-wind", "draft")
    ready.ok("push")
    assert share.stat(target.joinpath("a.txt")) is None
