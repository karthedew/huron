"""Development-only header-based principal resolution.

The last resort the service reaches for a request that carries neither a
bearer credential nor a session cookie, and only when it is configured for
``dev-headers`` authentication: the caller simply asserts who it is in
``X-Huron-Subject`` and which groups it belongs to in ``X-Huron-Groups``.
Nothing is proved, which is why :class:`DevHeaderResolver` refuses to exist
for any environment but development - the guard is in the constructor, so
no code path can hold a resolver that trusts unauthenticated headers
somewhere they must not be trusted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping


class DevHeaderResolver:
    """Take ``X-Huron-Subject`` and ``X-Huron-Groups`` headers as the caller's identity.

    Only constructible for the ``development`` environment: the constructor
    raises for any other ``env``, so a resolver that believes whatever the
    request says can never be wired into another deployment by mistake.
    Headers are looked up by their lower-cased names, as an ASGI server
    presents them.
    """

    def __init__(self, env: str):
        """Refuse to build a resolver for anything but development.

        Args:
            env: The deployment environment name; must be exactly
                ``"development"``.

        Raises:
            ValueError: If ``env`` is anything other than ``"development"``.
        """
        if env != "development":
            raise ValueError("dev headers are refused outside development")

    def resolve_headers(self, headers: Mapping[str, str]) -> Principal:
        """Build a principal from the request headers, taking them at their word.

        Args:
            headers: The request headers keyed by lower-cased name.
                ``x-huron-subject`` is required; ``x-huron-groups`` is an
                optional comma-separated list whose blank entries and
                surrounding whitespace are ignored.

        Returns:
            A principal for the asserted subject and groups with
            ``authentication_method`` ``"dev-headers"``, no scopes and no
            project restriction.

        Raises:
            AuthError: If ``x-huron-subject`` is missing or empty.
        """
        subject = headers.get("x-huron-subject")
        if not subject:
            raise AuthError("X-Huron-Subject is required")
        groups = frozenset(
            group.strip() for group in headers.get("x-huron-groups", "").split(",") if group.strip()
        )
        return Principal(subject, groups, authentication_method="dev-headers")


__all__ = ["DevHeaderResolver"]
