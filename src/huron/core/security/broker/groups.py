"""Current directory memberships through a caller-owned HTTP client."""

from __future__ import annotations

import unicodedata
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from huron.core.foundation.errors import DependencyUnavailable
from huron.core.security.broker._http import absolute_url


def parse_groups_response(body: object) -> frozenset[str]:
    """Validate directory membership without normalizing group names.

    Args:
        body: Decoded JSON document; unrelated top-level keys are ignored.

    Returns:
        Distinct directory groups, including unmapped groups.

    Raises:
        ValueError: If the document or a named group element is invalid.
    """
    if not isinstance(body, dict) or not isinstance(body.get("groups"), list):
        raise ValueError("groups must be an array in an object")
    groups: set[str] = set()
    for index, group in enumerate(body["groups"]):
        if (
            not isinstance(group, str)
            or not 1 <= len(group) <= 256
            or any(unicodedata.category(char) == "Cc" for char in group)
        ):
            raise ValueError(f"groups[{index}] is invalid: {group!r}")
        groups.add(group)
    return frozenset(groups)


class GroupDirectory(Protocol):
    """Read membership afresh, distinguishing unknown users from failed lookups."""

    async def groups_for(self, username: str) -> frozenset[str] | None:
        """Look up an already validated company username.

        Args:
            username: Verbatim company username.

        Returns:
            Current groups, or None only for an unknown user.
        """
        ...


class HttpGroupDirectory:
    """Fetch and validate one directory response without retries or caching."""

    def __init__(self, http: httpx.AsyncClient, *, url_template: str) -> None:
        """Capture an endpoint template without taking ownership of the client.

        Args:
            http: Caller-owned client with the deployment's timeout policy.
            url_template: Absolute HTTP URL with one username placeholder outside its host.

        Raises:
            ValueError: If the endpoint template cannot address a username.
        """
        candidate = url_template.replace("{username}", "username")
        if (
            url_template.count("{username}") != 1
            or not absolute_url(candidate)
            or "{username}" in urlsplit(url_template).netloc
            or "{username}" in urlsplit(url_template).fragment
        ):
            raise ValueError("directory URL needs one {username} outside an absolute HTTP host")
        self._http, self._url_template = http, url_template

    async def groups_for(self, username: str) -> frozenset[str] | None:
        """Fetch current groups with explicit unknown-user and outage outcomes.

        Args:
            username: Validated company username, encoded as one URL component.

        Returns:
            Validated groups, or None when the directory answers 404.

        Raises:
            DependencyUnavailable: If transport, status or response validation fails.
        """
        url = self._url_template.replace("{username}", quote(username, safe=""))
        try:
            response = await self._http.get(
                url, headers={"Accept": "application/json"}, follow_redirects=False
            )
        except httpx.TimeoutException as exc:
            raise DependencyUnavailable(
                context={"dependency": "group_directory", "reason": "timeout"}
            ) from exc
        except httpx.TransportError as exc:
            raise DependencyUnavailable(
                context={"dependency": "group_directory", "reason": "unreachable"}
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise DependencyUnavailable(
                context={
                    "dependency": "group_directory",
                    "reason": "status",
                    "status": response.status_code,
                }
            )
        try:
            return parse_groups_response(response.json())
        except ValueError as exc:
            raise DependencyUnavailable(
                context={"dependency": "group_directory", "reason": "malformed"}
            ) from exc
