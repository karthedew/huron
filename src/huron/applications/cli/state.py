"""The CLI's private state: tokens and working copies under ``$XDG_STATE_HOME/huron``."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from huron.applications.cli.errors import CliError, ExitCode

__all__ = ["Stage", "StagedAdd", "StateDir", "Tokens", "WorkingCopy", "state_root"]


@dataclass(frozen=True, slots=True)
class Tokens:
    """The Huron token and what is needed to renew it."""

    huron_token: str
    expires_at: float
    subject: str
    refresh_token: str | None = None


@dataclass(frozen=True, slots=True)
class WorkingCopy:
    """A checked-out collection: its identity and the version the stage is based on."""

    collection_id: str
    identifier: str
    version: int
    path: str | None


@dataclass(slots=True)
class StagedAdd:
    """A local file to copy into the collection at ``rel_path``; the stamp once copied."""

    rel_path: str
    source: str
    size: int
    sha256: str | None = None


@dataclass(slots=True)
class Stage:
    """Staged adds and removes of one working copy."""

    adds: list[StagedAdd] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """Whether nothing is staged."""
        return not self.adds and not self.removes

    def as_dict(self) -> dict[str, Any]:
        """Render for ``stage.json``."""
        return {"adds": [asdict(a) for a in self.adds], "removes": list(self.removes)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Stage:
        """Read ``stage.json``."""
        return cls([StagedAdd(**a) for a in data.get("adds", [])], list(data.get("removes", [])))


class StateDir:
    """Reads and writes the state directory; created with mode 0700."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> Path:
        """Create the directory if needed."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.root

    def read_tokens(self) -> Tokens | None:
        """The stored tokens; refused when the file is readable by others."""
        path = self.root / "tokens.json"
        if not path.exists():
            return None
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
            raise CliError(
                f"{path} must be owned by you with mode 0600",
                ExitCode.NOT_LOGGED_IN,
                hint=f"run: chmod 600 {path}, or huron login",
            )
        return Tokens(**json.loads(path.read_text()))

    def write_tokens(self, tokens: Tokens) -> None:
        """Store tokens with mode 0600."""
        self._write(self.ensure() / "tokens.json", asdict(tokens))

    def delete_tokens(self) -> bool:
        """Forget the tokens; returns whether any were stored."""
        path = self.root / "tokens.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def collection_dir(self, collection_id: str) -> Path:
        """The directory of one working copy."""
        return self.ensure() / "collections" / collection_id

    def read_copy(self, collection_id: str) -> WorkingCopy | None:
        """A working copy, if checked out."""
        data = self._read(self.collection_dir(collection_id) / "copy.json")
        return None if data is None else WorkingCopy(**data)

    def write_copy(self, copy: WorkingCopy) -> None:
        """Record a working copy."""
        self._write(self.collection_dir(copy.collection_id) / "copy.json", asdict(copy))

    def read_stage(self, collection_id: str) -> Stage:
        """The stage of a working copy (empty when none)."""
        data = self._read(self.collection_dir(collection_id) / "stage.json")
        return Stage() if data is None else Stage.from_dict(data)

    def write_stage(self, collection_id: str, stage: Stage) -> None:
        """Replace the stage of a working copy."""
        self._write(self.collection_dir(collection_id) / "stage.json", stage.as_dict())

    def read_draft(self, collection_id: str) -> dict[str, Any] | None:
        """The local metadata draft of a working copy."""
        return self._read(self.collection_dir(collection_id) / "metadata.draft.json")

    def write_draft(self, collection_id: str, document: dict[str, Any]) -> None:
        """Store a local metadata draft."""
        self._write(self.collection_dir(collection_id) / "metadata.draft.json", document)

    def delete_draft(self, collection_id: str) -> None:
        """Forget the local metadata draft."""
        (self.collection_dir(collection_id) / "metadata.draft.json").unlink(missing_ok=True)

    @contextmanager
    def locked(self, collection_id: str) -> Generator[None]:
        """Hold the working copy's lock; refuses when another push holds it."""
        path = self.collection_dir(collection_id)
        path.mkdir(parents=True, exist_ok=True)
        with (path / "lock").open("w") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CliError(
                    "another huron command is using this working copy", ExitCode.CONFLICT
                ) from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        data: dict[str, Any] = json.loads(path.read_text())
        return data

    def _write(self, path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        part = path.with_name(path.name + ".tmp")
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(part, path)


def state_root(environ: Mapping[str, str]) -> Path:
    """``$XDG_STATE_HOME/huron``."""
    base = environ.get("XDG_STATE_HOME") or str(
        Path(environ.get("HOME", "~")).expanduser() / ".local" / "state"
    )
    return Path(base) / "huron"
