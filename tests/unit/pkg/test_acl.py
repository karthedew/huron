"""ACL parsing, rendering and command invocation through a fake runner."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from huron.pkg.fs.acl import (
    Acl,
    AclEntry,
    AclError,
    CompletedRun,
    SubprocessRunner,
    acl_supported,
    parse_acl,
    read_acl,
    render_acl,
    write_acl,
)

GETFACL = """\
user::rwx
group::r-x
group:helio-contributors:rwx
mask::rwx
other::---
default:user::rwx
default:group::r-x
default:group:huron-platform-admins:rwx   # comment
default:other::---
"""


class FakeRunner:
    def __init__(self, result: CompletedRun) -> None:
        self.result = result
        self.calls: list[tuple[list[str], str | None]] = []

    def run(self, argv: Sequence[str], stdin: str | None = None) -> CompletedRun:
        self.calls.append((list(argv), stdin))
        return self.result


def test_parse_separates_access_and_default_entries() -> None:
    acl = parse_acl(GETFACL)
    assert AclEntry("group", "helio-contributors", "rwx") in acl.access
    assert AclEntry("group", "huron-platform-admins", "rwx") in acl.default
    assert AclEntry("mask", None, "rwx") not in acl.without_masks().access
    assert len(acl.default) == 4


def test_render_round_trips_ignoring_masks() -> None:
    acl = parse_acl(GETFACL)
    assert parse_acl(render_acl(acl)).without_masks() == acl.without_masks()
    first = render_acl(acl).splitlines()[0]
    assert first == "user::rwx"


def test_unreadable_entries_are_refused() -> None:
    with pytest.raises(AclError):
        parse_acl("bogus::rwx")
    with pytest.raises(AclError):
        parse_acl("user:rwx")


def test_read_and_write_invoke_getfacl_and_setfacl(tmp_path: Path) -> None:
    runner = FakeRunner(CompletedRun(0, GETFACL, ""))
    assert read_acl(tmp_path, runner) == parse_acl(GETFACL)
    acl = Acl(frozenset({AclEntry("other", None, "---")}))
    write_acl(tmp_path, acl, runner)
    argv, stdin = runner.calls[-1]
    assert argv == ["setfacl", "--set-file=-", str(tmp_path)]
    assert stdin == "other::---\n"
    assert acl_supported(tmp_path, runner) is True


def test_failures_raise_with_the_command_error(tmp_path: Path) -> None:
    runner = FakeRunner(CompletedRun(1, "", "Operation not supported\n"))
    with pytest.raises(AclError) as raised:
        read_acl(tmp_path, runner)
    assert raised.value.context["stderr"] == "Operation not supported"
    with pytest.raises(AclError):
        write_acl(tmp_path, Acl(), runner)
    assert acl_supported(tmp_path, runner) is False


def test_subprocess_runner_reports_missing_executables() -> None:
    runner = SubprocessRunner()
    assert runner.run(["huron-no-such-command"]).returncode == 127
    done = runner.run(["cat"], stdin="hi")
    assert (done.returncode, done.stdout) == (0, "hi")
