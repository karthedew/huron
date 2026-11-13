"""The upload stack of the integration tier removes its containers when its start fails.

The container runtime is faked at the ``subprocess`` boundary: each ``docker`` command is
recorded, and a chosen ``docker run`` fails.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.support import uploadstack
from tests.support.uploadstack import HOOK_TIMEOUT, UploadStack


class FakeDocker:
    """Records each ``docker`` command; a ``docker run`` of a name in ``failing`` fails."""

    def __init__(self, *failing: str) -> None:
        self.commands: list[list[str]] = []
        self._failing = failing

    def run(self, command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        name = next((word for word in command if word.startswith("--name=")), "")
        if command[1] == "run" and name.removeprefix("--name=") in self._failing:
            return subprocess.CompletedProcess(command, 125, "", "the run fails")
        return subprocess.CompletedProcess(command, 0, "", "")

    def removed(self) -> list[str]:
        """The containers that ``docker rm --force`` removed, in order."""
        return [command[-1] for command in self.commands if command[1:3] == ["rm", "--force"]]


@pytest.fixture
def stack(tmp_path: Path) -> UploadStack:
    (tmp_path / "lake").mkdir()
    return UploadStack(tmp_path / "lake", tmp_path)


def test_a_failed_proxy_start_removes_the_proxy_and_tusd(
    stack: UploadStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker(stack.proxy)
    monkeypatch.setattr(uploadstack.subprocess, "run", docker.run)
    with pytest.raises(AssertionError, match="the run fails"):
        stack.start(8080)
    assert docker.removed() == [stack.proxy, stack.tusd]


def test_a_failed_tusd_start_removes_the_container_that_the_run_can_leave(
    stack: UploadStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker(stack.tusd)
    monkeypatch.setattr(uploadstack.subprocess, "run", docker.run)
    with pytest.raises(AssertionError, match="the run fails"):
        stack.start(8080)
    assert docker.removed() == [stack.tusd]
    assert not any(stack.proxy in " ".join(command) for command in docker.commands)


def test_a_proxy_that_never_gets_ready_removes_both_containers(
    stack: UploadStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr(uploadstack.subprocess, "run", docker.run)
    monkeypatch.setattr(uploadstack, "DEADLINE", 0.0)
    with pytest.raises(AssertionError, match="the upload proxy is not ready"):
        stack.start(8080)
    assert docker.removed() == [stack.proxy, stack.tusd]


def test_a_started_stack_removes_its_containers_at_close(
    stack: UploadStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr(uploadstack.subprocess, "run", docker.run)
    stack.start_tusd()
    stack.close()
    stack.close()
    assert docker.removed() == [stack.tusd]


def test_the_hook_timeout_is_the_flag_of_the_compose_file() -> None:
    assert HOOK_TIMEOUT == 60
    assert (
        f"-hooks-http-timeout={HOOK_TIMEOUT}s"
        in uploadstack.compose_service("uploads", {})["command"]
    )
