"""Standalone identity fixtures and an in-process group directory."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

import httpx
import yaml
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.requests import Request

DEFAULT_IDENTITIES: Final = Path(__file__).with_name("identities.yaml")
COMPANY_USERNAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}")
GroupsFailure = int | Literal["timeout", "unreachable", "malformed"]
_USER_KEYS = {"id", "username", "given_name", "family_name", "email", "groups"}


def _keys(value: object, expected: set[str], entry: str) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f"{entry}: expected exactly {sorted(expected)}")
    return value


@dataclass(frozen=True, slots=True)
class FakeUser:
    """An immutable mock person's IdP identity and directory membership."""

    id: str
    username: str
    given_name: str
    family_name: str
    email: str
    groups: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate identity fields and take an immutable copy of membership."""
        for name in _USER_KEYS - {"groups"}:
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"user {self.username!r}: {name} must be a string")
        try:
            UUID(self.id)
        except ValueError as error:
            raise ValueError(f"user {self.username!r}: invalid id") from error
        if COMPANY_USERNAME.fullmatch(self.username) is None:
            raise ValueError(f"user {self.username!r}: invalid username")
        if not isinstance(self.groups, (list, tuple)):
            raise ValueError(f"user {self.username!r}: groups must be a list or tuple")
        for group in self.groups:
            if (
                not isinstance(group, str)
                or not 1 <= len(group) <= 256
                or any(unicodedata.category(char) == "Cc" for char in group)
            ):
                raise ValueError(f"user {self.username!r}: invalid group {group!r}")
        object.__setattr__(self, "groups", tuple(self.groups))


@dataclass(frozen=True, slots=True)
class Identities:
    """A read-only directory snapshot shared by the identity-provider fakes."""

    organization: str
    users: Mapping[str, FakeUser]

    def __post_init__(self) -> None:
        """Copy the directory and reject inconsistent keys or reused subjects."""
        if not isinstance(self.organization, str):
            raise ValueError("organization must be a string")
        users = dict(self.users)
        seen: set[UUID] = set()
        for username, user in users.items():
            if username != user.username:
                raise ValueError(f"user {username!r}: directory key differs from username")
            subject = UUID(user.id)
            if subject in seen:
                raise ValueError(f"user {username!r}: duplicate id")
            seen.add(subject)
        object.__setattr__(self, "users", MappingProxyType(users))

    @classmethod
    def load(cls, path: Path = DEFAULT_IDENTITIES) -> Identities:
        """Load the exact version-one YAML contract, naming any invalid entry.

        Args:
            path: The identity fixture to read.

        Returns:
            An immutable snapshot of the people in the fixture.

        Raises:
            ValueError: A fixture entry violates the version-one contract.
        """
        with path.open() as stream:
            document = _keys(yaml.safe_load(stream), {"version", "organization", "users"}, "root")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("version must be 1")
        if not isinstance(document["users"], list):
            raise ValueError("users must be a list")
        users: dict[str, FakeUser] = {}
        for index, entry in enumerate(document["users"]):
            try:
                fields = _keys(entry, _USER_KEYS, f"users[{index}]")
                if not isinstance(fields["groups"], list):
                    raise ValueError("groups must be a list")
                user = FakeUser(**fields)
                if user.username in users:
                    raise ValueError(f"duplicate username {user.username!r}")
                users[user.username] = user
            except ValueError as error:
                raise ValueError(f"users[{index}]: {error}") from error
        return cls(document["organization"], users)

    def with_user(self, user: FakeUser) -> Identities:
        """Return a new directory, replacing any person with this username.

        Args:
            user: The person to add or replace.

        Returns:
            A new snapshot preserving every other person.

        Raises:
            ValueError: The subject is already held by a different username.
        """
        return Identities(self.organization, {**self.users, user.username: user})

    def user(self, username: str) -> FakeUser:
        """Look up a person by their directory username.

        Args:
            username: The exact, case-sensitive username.

        Returns:
            The registered person.

        Raises:
            KeyError: No person has this username.
        """
        return self.users[username]


class FakeGroupDirectory:
    """Serve directory snapshots with persistent Python-only fault controls."""

    def __init__(self, identities: Identities) -> None:
        """Create an isolated service over an immutable directory.

        Args:
            identities: The people and groups this service exposes.
        """
        self._lock = Lock()
        self._identities = identities
        self._failures: dict[str | None, GroupsFailure] = {}
        self._requests: list[str] = []
        self._app = Starlette(routes=[Route("/users/{username}/groups", self._groups)])

    @property
    def app(self) -> Starlette:
        """Return the single app shared by synchronous and async clients."""
        with self._lock:
            return self._app

    def inject(self, failure: GroupsFailure | None, *, username: str | None = None) -> None:
        """Set or clear a user-specific fault, or the fallback global fault.

        Args:
            failure: An HTTP status or transport/body fault; None clears this scope.
            username: The affected user, or None for the global fallback.
        """
        with self._lock:
            if failure is None:
                self._failures.pop(username, None)
            else:
                self._failures[username] = failure

    @property
    def requests(self) -> tuple[str, ...]:
        """Return decoded usernames in request-arrival order."""
        with self._lock:
            return tuple(self._requests)

    async def _groups(self, request: Request) -> JSONResponse:
        username = request.path_params["username"]
        with self._lock:
            self._requests.append(username)
            failure = self._failures.get(username, self._failures.get(None))
            user = self._identities.users.get(username)
        if isinstance(failure, int):
            return JSONResponse({"error": "injected"}, status_code=failure)
        if failure == "timeout":
            raise httpx.ReadTimeout("injected")
        if failure == "unreachable":
            raise httpx.ConnectError("injected")
        if failure == "malformed":
            return JSONResponse({"groups": "not-a-list"})
        if user is None:
            return JSONResponse({"detail": "unknown user"}, status_code=404)
        return JSONResponse({"groups": sorted(user.groups)})


def app_from_environment() -> Starlette:
    """Build the standalone service from FAKE_IDENTITIES or the bundled fixture."""
    return FakeGroupDirectory(
        Identities.load(Path(os.environ.get("FAKE_IDENTITIES", DEFAULT_IDENTITIES)))
    ).app
