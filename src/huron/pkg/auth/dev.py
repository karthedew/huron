"""Development-only header-based principal resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping


class DevHeaderResolver:
    def __init__(self, env: str):
        if env != "development":
            raise ValueError("dev headers are refused outside development")

    def resolve_headers(self, headers: Mapping[str, str]) -> Principal:
        subject = headers.get("x-huron-subject")
        if not subject:
            raise AuthError("X-Huron-Subject is required")
        groups = frozenset(
            group.strip() for group in headers.get("x-huron-groups", "").split(",") if group.strip()
        )
        return Principal(subject, groups, authentication_method="dev-headers")


__all__ = ["DevHeaderResolver"]
