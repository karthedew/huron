"""POSIX ACLs read with ``getfacl`` and written with ``setfacl``."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

__all__ = [
    "Acl",
    "AclEntry",
    "AclError",
    "CompletedRun",
    "Runner",
    "SubprocessRunner",
    "acl_supported",
    "parse_acl",
    "read_acl",
    "render_acl",
    "write_acl",
]

ACL_FAILED = register("ACL_FAILED", 500, "ACL operation failed")

type Tag = Literal["user", "group", "other", "mask"]

_TAGS: dict[str, Tag] = {"user": "user", "group": "group", "other": "other", "mask": "mask"}


class AclError(HuronError):
    """Reading or writing an ACL failed."""

    error_code = ACL_FAILED


@dataclass(frozen=True, slots=True)
class AclEntry:
    """One ACL entry; ``qualifier`` is ``None`` for the owning user, owning group and other."""

    tag: Tag
    qualifier: str | None
    perms: str

    def render(self) -> str:
        """Render in getfacl syntax, for example ``group:helio:r-x``."""
        return f"{self.tag}:{self.qualifier or ''}:{self.perms}"


@dataclass(frozen=True, slots=True)
class Acl:
    """The access ACL of a path and, for directories, its default ACL."""

    access: frozenset[AclEntry] = field(default_factory=frozenset)
    default: frozenset[AclEntry] = field(default_factory=frozenset)

    def without_masks(self) -> Acl:
        """Return the ACL with mask entries dropped, for comparisons."""
        return Acl(
            frozenset(entry for entry in self.access if entry.tag != "mask"),
            frozenset(entry for entry in self.default if entry.tag != "mask"),
        )


@dataclass(frozen=True, slots=True)
class CompletedRun:
    """The outcome of running a command."""

    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs a command with optional standard input."""

    def run(self, argv: Sequence[str], stdin: str | None = None) -> CompletedRun:
        """Run ``argv`` and return its outcome."""
        ...


class SubprocessRunner:
    """Runs commands with :mod:`subprocess`."""

    def run(self, argv: Sequence[str], stdin: str | None = None) -> CompletedRun:
        """Run ``argv``; a missing executable becomes return code 127."""
        try:
            done = subprocess.run(
                list(argv), input=stdin, capture_output=True, text=True, check=False
            )
        except FileNotFoundError as error:
            return CompletedRun(127, "", str(error))
        return CompletedRun(done.returncode, done.stdout, done.stderr)


def parse_acl(text: str) -> Acl:
    """Parse ``getfacl --omit-header --no-effective`` output."""
    access: set[AclEntry] = set()
    default: set[AclEntry] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        target = access
        if line.startswith("default:"):
            target = default
            line = line.removeprefix("default:")
        target.add(_parse_entry(line))
    return Acl(frozenset(access), frozenset(default))


def render_acl(acl: Acl) -> str:
    """Render ``acl`` as ``setfacl --set-file`` input, entries sorted for determinism."""
    lines = [entry.render() for entry in _sorted(acl.access)]
    lines += ["default:" + entry.render() for entry in _sorted(acl.default)]
    return "\n".join(lines) + "\n"


def read_acl(path: Path, runner: Runner) -> Acl:
    """Read the ACL of ``path``; raises :class:`AclError` when ``getfacl`` fails."""
    done = runner.run(["getfacl", "--absolute-names", "--omit-header", "--no-effective", str(path)])
    if done.returncode != 0:
        raise AclError("getfacl failed", {"path": str(path), "stderr": done.stderr.strip()})
    return parse_acl(done.stdout)


def write_acl(path: Path, acl: Acl, runner: Runner) -> None:
    """Replace the whole ACL of ``path``; raises :class:`AclError` when ``setfacl`` fails."""
    done = runner.run(["setfacl", "--set-file=-", str(path)], stdin=render_acl(acl))
    if done.returncode != 0:
        raise AclError("setfacl failed", {"path": str(path), "stderr": done.stderr.strip()})


def acl_supported(path: Path, runner: Runner) -> bool:
    """Return whether ACLs can be read at ``path`` with the installed tools."""
    done = runner.run(["getfacl", "--absolute-names", "--omit-header", str(path)])
    return done.returncode == 0


def _parse_entry(text: str) -> AclEntry:
    parts = text.split(":")
    if len(parts) != 3 or parts[0] not in _TAGS:
        raise AclError("unreadable ACL entry", {"entry": text})
    tag, qualifier, perms = parts
    return AclEntry(_TAGS[tag], qualifier or None, perms)


def _sorted(entries: Iterable[AclEntry]) -> list[AclEntry]:
    order = {"user": 0, "group": 1, "mask": 2, "other": 3}
    return sorted(entries, key=lambda entry: (order[entry.tag], entry.qualifier or ""))
