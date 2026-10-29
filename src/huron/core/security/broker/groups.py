"""The LDAP group directory consulted at token exchange."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import httpx

from huron.pkg.errors import HuronError, register

__all__ = ["GroupDirectory", "GroupDirectoryUnavailable", "HttpGroupDirectory"]

GROUP_DIRECTORY_UNAVAILABLE = register(
    "GROUP_DIRECTORY_UNAVAILABLE", 503, "Group directory unavailable"
)


class GroupDirectoryUnavailable(HuronError):
    """The group directory could not answer."""

    error_code = GROUP_DIRECTORY_UNAVAILABLE


class GroupDirectory(Protocol):
    """Looks up the LDAP groups of a user."""

    async def groups_for(self, username: str) -> frozenset[str]:
        """The user's groups; empty for an unknown user."""
        ...


class HttpGroupDirectory:
    """``GET <base>/users/{username}/groups`` answering ``{"groups": [...]}``."""

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    async def groups_for(self, username: str) -> frozenset[str]:
        """The user's groups; a 404 means no groups; anything else unexpected is unavailable."""
        url = f"{self._base_url}/users/{quote(username, safe='')}/groups"
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as error:
            raise GroupDirectoryUnavailable("group directory is unreachable") from error
        if response.status_code == 404:
            return frozenset()
        if response.status_code != 200:
            raise GroupDirectoryUnavailable(
                "group directory failed", {"status": response.status_code}
            )
        try:
            groups = response.json()["groups"]
        except (ValueError, KeyError, TypeError) as error:
            raise GroupDirectoryUnavailable("group directory answer is unreadable") from error
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise GroupDirectoryUnavailable("group directory answer is unreadable")
        return frozenset(groups)
